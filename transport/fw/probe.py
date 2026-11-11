"""What is on a serial port, found without resetting the board.

The USB descriptor names the chip bridging USB to UART, so it only shortlists
ports. Asking `sys.version` identifies our firmware. Identifying a bare ESP32
needs the ROM bootloader, which resets the board, so that is in
`transport.bench.rom`.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Any

from shared import fw_api
from transport.fw import link

ESPRESSIF_VID = 0x303A

BRIDGE_VIDS = {
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340/CH341/CH9102",
    0x0403: "FTDI",
}

PROBE_TIMEOUT = 0.6
BOOT_TIMEOUT = 2.5


class Silicon(enum.Enum):
    """What a port's USB vendor id says about it."""

    ESPRESSIF = "espressif"
    BRIDGE = "bridge"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One attached port and its USB descriptor."""

    device: str
    vid: int | None
    pid: int | None
    description: str
    silicon: Silicon

    @property
    def plausible(self) -> bool:
        """Return whether the vendor id is Espressif or a known bridge."""
        return self.silicon is not Silicon.OTHER

    @property
    def vidpid(self) -> str:
        """Return the vendor and product ids as `vvvv:pppp`."""
        if self.vid is None:
            return "?"
        return f"{self.vid:04x}:{self.pid or 0:04x}"


def _silicon(vid: int | None) -> Silicon:
    """Return the silicon class of a vendor id."""
    if vid == ESPRESSIF_VID:
        return Silicon.ESPRESSIF
    return Silicon.BRIDGE if vid in BRIDGE_VIDS else Silicon.OTHER


def candidates() -> tuple[Candidate, ...]:
    """Return every attached serial port."""
    from serial.tools import list_ports

    return tuple(
        Candidate(
            device=port.device,
            vid=port.vid,
            pid=port.pid,
            description=port.description or "",
            silicon=_silicon(port.vid),
        )
        for port in list_ports.comports()
    )


def plausible_ports() -> tuple[str, ...]:
    """Return the attached ports whose vendor id is Espressif or a known bridge."""
    return tuple(c.device for c in candidates() if c.plausible)


def attached(port: str) -> Candidate | None:
    """Return the named port if it is attached now, else None."""
    return next((c for c in candidates() if c.device == port), None)


def find_port(port: str | None = None) -> str:
    """Return the named port if it is attached, or else the only plausible one.

    Raises LinkError when the named port is gone, or when no port or several are
    plausible.
    """
    shortlist = plausible_ports()
    if port is not None:
        if attached(port) is not None:
            return port
        plausible = ", ".join(shortlist) or "none"
        raise link.LinkError(
            f"nothing is attached on {port}; ports that could carry a board: {plausible}"
        )
    if not shortlist:
        raise link.LinkError("no port that could carry a board is attached")
    only, *rest = shortlist
    if rest:
        raise link.LinkError(f"several ports could, name one: {', '.join(shortlist)}")
    return only


# ── What the port turned out to be ───────────────────────────────────────────


class Finding(enum.Enum):
    """What a probe found, ordered from most to least of the stack answering."""

    RUNNING = "running"
    INCOMPATIBLE = "incompatible"
    SILENT = "silent"
    ABSENT = "absent"

    @property
    def ok(self) -> bool:
        """Return whether the bench can use this port."""
        return self is Finding.RUNNING


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one port turned out to be, with a sentence for the operator."""

    finding: Finding
    port: str
    sentence: str
    fields: tuple[tuple[str, str], ...] = ()
    version: str | None = None
    silicon: Silicon = Silicon.OTHER

    def __bool__(self) -> bool:
        """Return whether the port is usable."""
        return self.finding.ok


def _text(raw: Any) -> str:
    """Return a fixed-width firmware string as the text it holds."""
    if isinstance(raw, bytes):
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    return str(raw)


def _ask(port: str, boot_timeout: float) -> Any:
    """Return the `sys.version` reply, retrying on timeout until `boot_timeout` runs out.

    Opening the port toggles DTR and RTS, which resets most development boards,
    so the first requests can reach a chip that is still booting.
    """
    with link.FirmwareLink(port, timeout=PROBE_TIMEOUT) as opened:
        deadline = time.monotonic() + boot_timeout
        while True:
            try:
                return opened.sys.version()
            except link.LinkTimeout:
                if time.monotonic() >= deadline:
                    raise


def identify(port: str, *, boot_timeout: float = BOOT_TIMEOUT) -> Verdict:
    """Return what is on this port, asking only the running app.

    The board is usable when its backend and version are compatible with this
    build's `fw_api`.
    """
    candidate = attached(port)
    if candidate is None:
        return Verdict(Finding.ABSENT, port, f"nothing is attached on {port} any more")

    descriptor = (
        (f"{candidate.vidpid} {candidate.description}").strip()
        if candidate.vid is not None
        else candidate.description
    )
    port_fields = (("port", port), ("usb", descriptor))

    try:
        reply = _ask(port, boot_timeout)
    except link.LinkTimeout:
        return Verdict(
            Finding.SILENT,
            port,
            _silence(port, candidate.silicon),
            port_fields,
            silicon=candidate.silicon,
        )
    except Exception as exc:
        return Verdict(
            Finding.ABSENT,
            port,
            f"{port} would not open: {type(exc).__name__}: {exc}",
            port_fields,
            silicon=candidate.silicon,
        )

    running = _text(reply.version)
    backend = _text(reply.backend)
    fields = (
        *port_fields,
        ("backend", backend),
        ("version", running),
        ("idf", _text(reply.idf)),
        ("reset reason", str(reply.reset_reason)),
    )

    if not fw_api.compatible(backend, running):
        return Verdict(
            Finding.INCOMPATIBLE,
            port,
            f"the board is {backend} {running} and this build speaks "
            f"{fw_api.FW_API_BACKEND} {fw_api.FW_API_VERSION}, so the link is "
            f"unusable. Flash it",
            fields,
            running,
            candidate.silicon,
        )

    return Verdict(
        Finding.RUNNING,
        port,
        f"{backend} {running} is answering on {port}",
        fields,
        running,
        candidate.silicon,
    )


def _silence(port: str, silicon: Silicon) -> str:
    """Return the operator's sentence for a port that answers no RPC."""
    if silicon is Silicon.ESPRESSIF:
        return (
            f"Espressif silicon on {port} that answers no RPC. It has no working "
            f"firmware, or it is held in reset"
        )
    if silicon is Silicon.BRIDGE:
        return (
            f"a USB-UART bridge on {port} that answers no RPC. Either the board "
            f"behind it has no firmware, or it is not a board"
        )
    return f"nothing on {port} answers RPC, and its descriptor says it is not a board"
