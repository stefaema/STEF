"""Who is on a port, asked without disturbing whoever it is.

A USB descriptor names the chip bridging to a UART, never what is on the far
side of that UART, so it can nominate a port and never prove one. Proof comes
from talking. This module does the two questions that cost nothing to ask: what
the descriptor says, and whether our firmware answers. Telling a bare ESP32
apart from something else entirely needs the ROM bootloader, which resets the
board, so it lives in `transport.bench.rom` and not here.
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
BOOT_GRACE = 2.5


class Silicon(enum.Enum):
    """How much the descriptor alone settles."""

    ESPRESSIF = "espressif"
    BRIDGE = "bridge"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One attached port, and what its descriptor is worth."""

    device: str
    vid: int | None
    pid: int | None
    description: str
    silicon: Silicon

    @property
    def plausible(self) -> bool:
        """Whether this port is worth talking to at all."""
        return self.silicon is not Silicon.OTHER

    @property
    def vidpid(self) -> str:
        """Return the identifier pair as it is written on a datasheet."""
        if self.vid is None:
            return "?"
        return f"{self.vid:04x}:{self.pid or 0:04x}"


def _silicon(vid: int | None) -> Silicon:
    """Return what a vendor id settles, which for a bridge vendor is nothing."""
    if vid == ESPRESSIF_VID:
        return Silicon.ESPRESSIF
    return Silicon.BRIDGE if vid in BRIDGE_VIDS else Silicon.OTHER


def candidates() -> tuple[Candidate, ...]:
    """Return every attached port, whether or not a board could be behind it."""
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
    """Return the ports a board might be on, which is a shortlist and not an answer."""
    return tuple(c.device for c in candidates() if c.plausible)


def attached(port: str) -> Candidate | None:
    """Return the named port as it is attached now, or None where it is not."""
    return next((c for c in candidates() if c.device == port), None)


def find_port(port: str | None = None) -> str:
    """Return the port to talk to: the named one if it is attached, or the only shortlisted one.

    Either way the answer is checked against what is attached now, so a port that
    has since gone is a refusal rather than a failure to open it.
    """
    shortlist = plausible_ports()
    if port is not None:
        if attached(port) is not None:
            return port
        seen = ", ".join(shortlist) or "none"
        raise link.LinkError(
            f"nothing is attached on {port}; ports that could carry a board: {seen}"
        )
    if not shortlist:
        raise link.LinkError("no port that could carry a board is attached")
    only, *rest = shortlist
    if rest:
        raise link.LinkError(f"several ports could, name one: {', '.join(shortlist)}")
    return only


# ── What the port turned out to be ───────────────────────────────────────────


class Finding(enum.Enum):
    """What asking settled, ordered by how much of the stack answered."""

    RUNNING = "running"
    STALE = "stale"
    PROTOCOL = "protocol"
    SILENT = "silent"
    ABSENT = "absent"

    @property
    def ok(self) -> bool:
        """Whether this is a port the bench can go on to use."""
        return self is Finding.RUNNING


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one port turned out to be, in the words an operator reads."""

    finding: Finding
    port: str
    sentence: str
    fields: tuple[tuple[str, str], ...] = ()
    version: str | None = None
    silicon: Silicon = Silicon.OTHER

    def __bool__(self) -> bool:
        """Return whether the port is usable, so a verdict reads like a check."""
        return self.finding.ok


def _text(raw: Any) -> str:
    """Return a fixed-width firmware string as the text it holds."""
    if isinstance(raw, bytes):
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    return str(raw)


def _ask(port: str, grace: float) -> Any:
    """Return what `sys.version` answers, retrying while the board may still be booting.

    Opening the port toggles DTR and RTS, which is the auto-reset circuit on most
    development boards, so the first request often reaches a chip that is still
    coming up. Retrying is the difference between "no firmware" and "not yet".
    """
    with link.FirmwareLink(port, timeout=PROBE_TIMEOUT) as opened:
        deadline = time.monotonic() + grace
        while True:
            try:
                return opened.sys.version()
            except link.LinkTimeout:
                if time.monotonic() >= deadline:
                    raise


def identify(
    port: str, expected: str | None = None, *, grace: float = BOOT_GRACE
) -> Verdict:
    """Return what is on this port, asking the app and never the bootloader.

    `expected` is the version this machine has installed. Without one the running
    firmware is reported and not judged, since nothing here says what it should
    have been.
    """
    seen = attached(port)
    if seen is None:
        return Verdict(Finding.ABSENT, port, f"nothing is attached on {port} any more")

    descriptor = (
        (f"{seen.vidpid} {seen.description}").strip()
        if seen.vid is not None
        else seen.description
    )
    common = (("port", port), ("usb", descriptor))

    try:
        reply = _ask(port, grace)
    except link.LinkTimeout:
        return Verdict(
            Finding.SILENT,
            port,
            _silence(port, seen.silicon),
            common,
            silicon=seen.silicon,
        )
    except Exception as exc:
        return Verdict(
            Finding.ABSENT,
            port,
            f"{port} would not open: {type(exc).__name__}: {exc}",
            common,
            silicon=seen.silicon,
        )

    running = _text(reply.version)
    fields = (
        *common,
        ("project", _text(reply.project)),
        ("version", running),
        ("idf", _text(reply.idf)),
        ("protocol", str(reply.protocol)),
        ("reset reason", str(reply.reset_reason)),
    )

    if reply.protocol != fw_api.RPC_PROTOCOL_VERSION:
        return Verdict(
            Finding.PROTOCOL,
            port,
            f"the board speaks protocol {reply.protocol} and this build speaks "
            f"{fw_api.RPC_PROTOCOL_VERSION}, so the link is unusable. Flash it",
            fields,
            running,
            seen.silicon,
        )

    if expected is not None and running != expected:
        return Verdict(
            Finding.STALE,
            port,
            f"your firmware, wrong build: {running} is running and {expected} "
            f"is installed. Flash it",
            fields,
            running,
            seen.silicon,
        )

    unjudged = "" if expected is not None else ", and no firmware is installed here"
    return Verdict(
        Finding.RUNNING,
        port,
        f"{_text(reply.project)} {running} is answering on {port}{unjudged}",
        fields,
        running,
        seen.silicon,
    )


def _silence(port: str, silicon: Silicon) -> str:
    """Return what silence means, which is as far as the descriptor can narrow it."""
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
