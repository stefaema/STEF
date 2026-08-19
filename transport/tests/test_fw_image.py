"""What counts as an installed image, and which one this build can talk to."""

import hashlib
import json

import pytest

from shared import fw_api
from transport import fw

BOOTLOADER = b"bootloader bytes"
APP = b"app bytes"


def install(
    root, version=None, chip="esp32c3", corrupt=False, manifest=True, backend=None
):
    """Write one release into the inventory, as a build would have packaged it."""
    version = fw_api.FW_API_VERSION if version is None else version
    backend = fw_api.FW_API_BACKEND if backend is None else backend
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
                "backend": backend,
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


# ── The one this build can talk to ───────────────────────────────────────────


def test_the_release_this_build_speaks_is_the_one_auto_names(inventory):
    install(inventory)
    assert fw.image.usable()[0].version == fw_api.FW_API_VERSION
    assert fw.image.resolve().version == fw_api.FW_API_VERSION


def test_nothing_installed_speaking_our_contract_settles_nothing(inventory):
    install(inventory, "0.0.9")
    assert fw.image.usable() == ()
    with pytest.raises(fw.image.ImageError, match="nothing installed speaks"):
        fw.image.resolve()


def test_another_backend_at_our_version_does_not_count_as_usable(inventory):
    install(inventory, backend="rp2040-drv8825")
    assert fw.image.usable() == ()


def test_a_named_version_is_taken_over_the_one_that_fits(inventory):
    install(inventory, "0.0.9")
    install(inventory)
    assert fw.image.resolve("0.0.9").version == "0.0.9"


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
