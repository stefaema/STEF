"""What counts as an installed image, and which one a board ought to be running."""

import hashlib
import json

import pytest

from transport import fw

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

    (directory / fw.image.MANIFEST).write_text(
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
    """Point the inventory at a scratch directory, so nothing reads the real machine."""
    bins = tmp_path / "firmware"
    monkeypatch.setattr(fw.image.paths, "firmware_bins", lambda: bins)
    return bins


# ── What is installed ────────────────────────────────────────────────────────


def test_a_release_carries_the_offsets_its_build_recorded(inventory):
    install(inventory, "0.3.1")
    release = fw.image.installed()[0]
    assert [b.offset for b in release.binaries] == [0x0, 0x10000]
    assert release.chip == "esp32c3"
    assert release.total == len(BOOTLOADER) + len(APP)


def test_a_directory_with_no_manifest_is_not_an_image_and_stops_nothing(inventory):
    install(inventory, "0.3.1")
    install(inventory, "notes", manifest=False)
    assert [r.version for r in fw.image.installed()] == ["0.3.1"]


def test_a_manifest_naming_a_file_that_is_not_there_is_refused(inventory):
    directory = install(inventory, "0.3.1")
    (directory / "app.bin").unlink()
    with pytest.raises(fw.image.ImageError, match="missing"):
        fw.image.read(directory)


def test_an_empty_inventory_is_empty_rather_than_an_error(inventory):
    assert fw.image.installed() == ()
    assert fw.image.versions() == (fw.image.AUTO,)


# ── The one this installation runs ───────────────────────────────────────────


def test_the_installed_release_is_what_a_board_ought_to_be_running(inventory):
    install(inventory, "0.3.1")
    assert fw.image.expected() == "0.3.1"
    assert fw.image.resolve().version == "0.3.1"


def test_nothing_installed_settles_nothing(inventory):
    assert fw.image.expected() is None


def test_several_installed_is_a_question_rather_than_the_newest(inventory):
    install(inventory, "0.2.9")
    install(inventory, "0.3.1")
    assert fw.image.expected() is None
    with pytest.raises(fw.image.ImageError, match="installing replaces"):
        fw.image.resolve()


def test_a_named_version_is_taken_over_the_installed_one(inventory):
    install(inventory, "0.2.9")
    install(inventory, "0.3.1")
    assert fw.image.resolve("0.2.9").version == "0.2.9"


def test_a_version_that_is_not_installed_names_what_is(inventory):
    install(inventory, "0.3.1")
    with pytest.raises(fw.image.ImageError, match="have: 0.3.1"):
        fw.image.resolve("9.9.9")


def test_no_firmware_at_all_says_to_import_some(inventory):
    with pytest.raises(fw.image.ImageError, match="import one first"):
        fw.image.resolve()


# ── Whether the image is still the one that was built ────────────────────────


def test_a_binary_that_no_longer_hashes_to_its_manifest_is_named(inventory):
    install(inventory, "0.3.1", corrupt=True)
    assert fw.image.altered(fw.image.installed()[0]) == ("app.bin",)


def test_an_untouched_release_alters_nothing(inventory):
    install(inventory, "0.3.1")
    assert fw.image.altered(fw.image.installed()[0]) == ()


def test_a_release_knows_which_silicon_it_was_built_for(inventory):
    install(inventory, "0.3.1", chip="esp32c3")
    release = fw.image.installed()[0]
    assert release.fits("ESP32-C3")
    assert not release.fits("esp32s3")
