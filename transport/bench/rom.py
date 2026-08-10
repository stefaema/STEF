"""What the ROM bootloader answers, for the questions a running firmware cannot.

Asking the app who it is only works while there is an app. A board that is
blank, half-flashed or running something that does not speak our protocol
answers nothing, and the descriptor cannot tell that apart from a USB-serial
adapter with a lathe behind it. The ROM can: it is in silicon, it is there
before any firmware, and it names its own chip.

The price is a reset into the bootloader, which stops whatever was running. So
nothing on the connect path comes here. This is bench work, and it wants the
port to itself.
"""

from __future__ import annotations

import contextlib
import importlib
import io
from dataclasses import dataclass
from typing import Any

from transport import fw_image

ROM_BAUD = 115200
FLASH_BAUD = 460800
CONNECT_ATTEMPTS = 2


class RomError(Exception):
    """The bootloader could not be reached, or refused what it was asked."""


def _esptool() -> Any:
    """Return the esptool module, saying plainly when the shell does not carry it."""
    try:
        import esptool
    except ImportError as exc:
        raise RomError(
            "esptool is not importable; enter the transport devShell"
        ) from exc
    return esptool


def _detect_chip() -> Any:
    """Return esptool's chip detection, which moved between its major versions."""
    found = getattr(_esptool(), "detect_chip", None)
    if found is not None:
        return found
    return importlib.import_module("esptool.cmds").detect_chip


@dataclass(frozen=True, slots=True)
class Rom:
    """What the bootloader said about the silicon it runs on."""

    chip: str
    description: str
    mac: str

    @property
    def fields(self) -> tuple[tuple[str, str], ...]:
        """Return what was learned, in the shape a result renders."""
        return (("chip", self.description), ("mac", self.mac))


def _mac(loader: Any) -> str:
    """Return the MAC as it is printed on a label, or say it would not answer."""
    try:
        return ":".join(f"{b:02x}" for b in loader.read_mac())
    except Exception:
        return "unreadable"


def detect(port: str) -> Rom:
    """Return what the ROM on this port says it is, resetting the board to ask.

    Raises rather than returning a verdict, because "the bootloader did not
    answer" is one outcome among several that only the caller can put in words.
    """
    detect_chip = _detect_chip()
    quiet = io.StringIO()
    try:
        with contextlib.redirect_stdout(quiet):
            loader = detect_chip(port, ROM_BAUD, connect_attempts=CONNECT_ATTEMPTS)
            try:
                found = Rom(
                    chip=getattr(loader, "CHIP_NAME", "unknown"),
                    description=loader.get_chip_description(),
                    mac=_mac(loader),
                )
            finally:
                with contextlib.suppress(Exception):
                    loader.hard_reset()
                with contextlib.suppress(Exception):
                    loader._port.close()
    except RomError:
        raise
    except Exception as exc:
        raise RomError(f"no bootloader answered on {port}: {exc}") from exc
    return found


# ── Putting an image on ──────────────────────────────────────────────────────


def _run(argv: list[str]) -> str:
    """Run one esptool command in this process and return what it printed."""
    esptool = _esptool()
    spoken = io.StringIO()
    try:
        with contextlib.redirect_stdout(spoken):
            esptool.main(argv)
    except SystemExit as exc:
        if exc.code:
            raise RomError(f"esptool refused: {spoken.getvalue().strip()}") from exc
    except Exception as exc:
        raise RomError(f"esptool failed: {exc}") from exc
    return spoken.getvalue()


def erase(port: str, chip: str) -> str:
    """Erase the whole flash, which is what makes a reflash a clean one."""
    return _run(["--port", port, "--chip", chip, "erase-flash"])


def write(port: str, release: fw_image.Release, binary: fw_image.Binary) -> str:
    """Write one of a release's binaries at the offset its build recorded."""
    return _run(
        [
            "--port",
            port,
            "--chip",
            release.chip,
            "--baud",
            str(FLASH_BAUD),
            "write-flash",
            "--flash-mode",
            release.flash_mode,
            "--flash-freq",
            release.flash_freq,
            "--flash-size",
            release.flash_size,
            hex(binary.offset),
            str(binary.path),
        ]
    )


def verify(port: str, release: fw_image.Release) -> tuple[str, ...]:
    """Return the binaries whose bytes on the board differ from the ones on disk.

    Reads flash back through the bootloader, so it answers on a board whose
    firmware does not run. That is the question `sys.version` cannot be asked.
    """
    differing = []
    for binary in release.binaries:
        try:
            _run(
                [
                    "--port",
                    port,
                    "--chip",
                    release.chip,
                    "--baud",
                    str(FLASH_BAUD),
                    "verify-flash",
                    hex(binary.offset),
                    str(binary.path),
                ]
            )
        except RomError:
            differing.append(binary.path.name)
    return tuple(differing)
