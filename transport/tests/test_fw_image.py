"""What counts as an installed image, and which one this machine says it runs."""

import hashlib
import json

import pytest

from transport import fw_image

BOOTLOADER = b"bootloader bytes"
APP = b"app bytes"


def install(root, version, chip="esp32c3", corrupt=False, manifest=True):
    """Write one release into the inventory, as a build would have packaged it."""
    directory = root / version
    directory.mkdir(parents=True)
    files = {"bootloader.bin": BOOTLOADER, "app.bin": APP}
    for name, body in files.items():
        (directory / name).write_bytes(body)
    if corrupt:
        (directory / "app.bin").write_bytes(APP + b"tampered")
    if not manifest:
        return directory

    (directory / fw_image.MANIFEST).write_text(
        json.dumps(
            {
                "version": version,
                "project": "stef-fw",
                "idf": "v5.2",
                "chip": chip,
                "flash_size": "4MB",
                "flash_mode": "dio",
                "flash_freq": "80m",
                "images": [
                    {
                        "offset": offset,
                        "file": name,
                        "sha256": hashlib.sha256(files[name]).hexdigest(),
                    }
                    for name, offset in (
                        ("bootloader.bin", "0x0"),
                        ("app.bin", "0x10000"),
                    )
                ],
            }
        )
    )
    return directory


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    """Point both roots at a scratch directory, so nothing reads the real machine."""
    bins = tmp_path / "firmware"
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(fw_image.paths, "firmware_bins", lambda: bins)
    monkeypatch.setattr(fw_image.paths, "config_dir", lambda: config)
    return bins


@pytest.fixture
def pin(inventory, tmp_path):
    """Return a way to write the version this machine declares it runs."""

    def declare(version):
        (tmp_path / "config" / fw_image.PIN_FILE).write_text(f'version = "{version}"\n')

    return declare


# ── What is installed ────────────────────────────────────────────────────────


def test_a_release_carries_the_offsets_its_build_recorded(inventory):
    install(inventory, "0.3.1")
    release = fw_image.installed()[0]
    assert [b.offset for b in release.binaries] == [0x0, 0x10000]
    assert release.chip == "esp32c3"
    assert release.total == len(BOOTLOADER) + len(APP)


def test_a_directory_with_no_manifest_is_not_an_image_and_stops_nothing(inventory):
    install(inventory, "0.3.1")
    install(inventory, "notes", manifest=False)
    assert [r.version for r in fw_image.installed()] == ["0.3.1"]


def test_a_manifest_naming_a_file_that_is_not_there_is_refused(inventory):
    directory = install(inventory, "0.3.1")
    (directory / "app.bin").unlink()
    with pytest.raises(fw_image.ImageError, match="missing"):
        fw_image.read(directory)


def test_an_empty_inventory_is_empty_rather_than_an_error(inventory):
    assert fw_image.installed() == ()
    assert fw_image.versions() == (fw_image.AUTO,)


# ── The one this installation runs ───────────────────────────────────────────


def test_a_pin_says_outright_what_should_be_running(inventory, pin):
    install(inventory, "0.2.9")
    install(inventory, "0.3.1")
    pin("0.3.1")
    assert fw_image.expected() == "0.3.1"
    assert fw_image.resolve().version == "0.3.1"


def test_one_installed_release_is_the_only_answer_available_and_not_a_guess(inventory):
    install(inventory, "0.3.1")
    assert fw_image.expected() == "0.3.1"


def test_several_installed_and_no_pin_is_a_question_rather_than_the_newest(inventory):
    install(inventory, "0.2.9")
    install(inventory, "0.3.1")
    assert fw_image.expected() is None
    with pytest.raises(fw_image.ImageError, match="none is pinned"):
        fw_image.resolve()


def test_a_named_version_is_taken_over_the_pin(inventory, pin):
    install(inventory, "0.2.9")
    install(inventory, "0.3.1")
    pin("0.3.1")
    assert fw_image.resolve("0.2.9").version == "0.2.9"


def test_a_version_that_is_not_installed_names_what_is(inventory):
    install(inventory, "0.3.1")
    with pytest.raises(fw_image.ImageError, match="have: 0.3.1"):
        fw_image.resolve("9.9.9")


def test_no_firmware_at_all_says_to_import_some(inventory):
    with pytest.raises(fw_image.ImageError, match="import one first"):
        fw_image.resolve()


# ── Whether the image is still the one that was built ────────────────────────


def test_a_binary_that_no_longer_hashes_to_its_manifest_is_named(inventory):
    install(inventory, "0.3.1", corrupt=True)
    assert fw_image.altered(fw_image.installed()[0]) == ("app.bin",)


def test_an_untouched_release_alters_nothing(inventory):
    install(inventory, "0.3.1")
    assert fw_image.altered(fw_image.installed()[0]) == ()


def test_a_release_knows_which_silicon_it_was_built_for(inventory):
    install(inventory, "0.3.1", chip="esp32c3")
    release = fw_image.installed()[0]
    assert release.fits("ESP32-C3")
    assert not release.fits("esp32s3")
