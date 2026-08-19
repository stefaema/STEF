"""The link this package owns, and what it is doing right now."""

from __future__ import annotations

from typing import Any

from shared.bench_api import Option, SubsystemState
from transport import fw

AUTO = "auto"

_link: Any = None
_failure: str | None = None
_sink: Any = None


# ── What is on the far end ───────────────────────────────────────────────────


def serial_ports() -> tuple[Option, ...]:
    """Return every attached port, each with a label saying what it looks like.

    Every port, not only the shortlist. What the descriptor settles is what
    `auto` may pick, never what an operator may choose, and a board behind a
    bridge nobody recognises is exactly the case where naming the port by hand is
    the way through. The likely ones sort first so the list reads as a
    recommendation rather than a filter.
    """
    ranked = sorted(fw.probe.candidates(), key=lambda c: (not c.plausible, c.device))
    return (Option(AUTO, AUTO), *(Option(c.device, _label(c)) for c in ranked))


def _label(candidate: fw.probe.Candidate) -> str:
    """Return what to call one port, which is its name plus whatever it admits to."""
    if not candidate.plausible:
        return candidate.device
    return f"{candidate.device} ({candidate.description or candidate.vidpid})"


def named_port(port: str) -> str | None:
    """Return the port the operator chose, or None where they left the choice open."""
    return None if port == AUTO else port


def pinned_version() -> str | None:
    """Return the version this machine says it runs, treating an unreadable pin as none."""
    try:
        return fw.image.expected()
    except fw.image.ImageError:
        return None


# ── The link ─────────────────────────────────────────────────────────────────


def state() -> SubsystemState:
    """Return whether the board is reachable, which is what having a link says."""
    if _link is not None:
        return SubsystemState.UP
    return SubsystemState.ERROR if _failure else SubsystemState.DOWN


def firmware() -> Any:
    """Return the open link, or say there is nothing to call through."""
    if _link is None:
        raise fw.link.LinkError("the transport is not connected")
    return _link


def logs_to(sink: Any) -> None:
    """Take the sink the firmware's own log lines are handed to."""
    global _sink
    _sink = sink


def open_link(port: str) -> str:
    """Open the link, atomically, so a half-open one is not representable."""
    global _link, _failure
    chosen = fw.probe.find_port(named_port(port))
    try:
        opened = fw.link.FirmwareLink(chosen, on_log=_sink)
    except Exception as exc:
        _failure = f"{type(exc).__name__}: {exc}"
        raise
    _failure = None
    _link = opened
    return chosen


def close_link() -> None:
    """Close the link and everything it started, whatever state it was in."""
    global _link, _failure
    open_now, _link = _link, None
    _failure = None
    if open_now is not None:
        open_now.close()
