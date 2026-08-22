"""The link this package owns, and what it is doing right now."""

from __future__ import annotations

from typing import Any

from shared.subsystem import SubsystemLinkState
from transport import fw

AUTO = "auto"

_link: Any = None
_failure: str | None = None


# ── What is on the far end ───────────────────────────────────────────────────


def named_port(port: str) -> str | None:
    """Return the port the operator chose, or None where they left the choice open."""
    return None if port == AUTO else port


# ── The link ─────────────────────────────────────────────────────────────────


def link_state() -> SubsystemLinkState:
    """Return whether the board is reachable, which is what having a link says."""
    if _link is not None:
        return SubsystemLinkState.UP
    return SubsystemLinkState.ERROR if _failure else SubsystemLinkState.DOWN


def firmware() -> Any:
    """Return the open link, or say there is nothing to call through."""
    if _link is None:
        raise fw.link.LinkError("the transport is not connected")
    return _link


def open_link(port: str) -> str:
    """Open the link, atomically, so a half-open one is not representable."""
    global _link, _failure
    chosen = fw.probe.find_port(named_port(port))
    try:
        opened = fw.link.FirmwareLink(chosen, on_log=fw.logs.forward)
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
