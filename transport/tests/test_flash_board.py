"""What FlashBoard says it left on the board, however it ended."""

from types import SimpleNamespace

import pytest

from shared.diagnostics import PASSED, WARNED
from transport import fw
from transport.bench import prelink, rom

PORT = "/dev/ttyUSB0"


class Image:
    version = "v9.9.9"
    chip = "esp32"
    binaries = ()

    def fits(self, chip):
        return True


@pytest.fixture
def board_without_firmware(monkeypatch):
    """A board on PORT whose firmware is silent, and a release that matches its chip."""
    monkeypatch.setattr(fw.image, "resolve", lambda chosen: Image())
    monkeypatch.setattr(fw.image, "altered", lambda image: ())
    monkeypatch.setattr(prelink, "_port_now", lambda chosen: PORT)
    silent = fw.probe.Verdict(fw.probe.Finding.SILENT, PORT, "nothing answers", ())
    monkeypatch.setattr(fw.probe, "identify", lambda port: silent)
    monkeypatch.setattr(
        rom,
        "detect",
        lambda port: SimpleNamespace(chip="esp32", description="ESP32", fields=()),
    )


def ended(unlinked):
    found = unlinked.run_test("prelink.FlashBoard", {}, lambda record: None)
    return found.outcomes[-1]


def test_a_flash_that_failed_after_the_erase_says_the_board_needs_flashing(
    unlinked, board_without_firmware, monkeypatch
):
    def erase_fails(port, chip):
        raise rom.RomError("the bootloader stopped answering")

    monkeypatch.setattr(rom, "erase", erase_fails)

    left = ended(unlinked)

    assert left.end and left.status is WARNED
    assert "Flash it again" in left.detail


def test_a_flash_that_never_reached_the_erase_says_the_flash_was_not_touched(
    unlinked, board_without_firmware, monkeypatch
):
    monkeypatch.setattr(fw.image, "altered", lambda image: ("app.bin",))

    left = ended(unlinked)

    assert left.status is PASSED
    assert left.detail == "the board's flash was not touched"
