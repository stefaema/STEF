"""The camera this package owns, and what it is doing right now."""

from __future__ import annotations

from typing import Any

from capture import probe
from portable.ccapi import Camera, CameraConfig, Credentials, LinkState
from shared import config, logs
from shared.subsystem import SubsystemState

PACKAGE = "capture"
SETTINGS = f"camera{config.SUFFIX}"
AUTO = "auto"

log = logs.component("capture")

_camera: Camera | None = None
_failure: str | None = None


# ── What this machine was told ───────────────────────────────────────────────


def settings() -> dict[str, Any]:
    """Return this machine's camera settings, its own laid over the shipped ones."""
    try:
        return config.get(PACKAGE, SETTINGS).get("camera", {})
    except config.ConfigError:
        return {}


def pinned_host() -> str | None:
    """Return the address this machine was told to use, or None where it was not."""
    return settings().get("host") or None


def configured(host: str) -> CameraConfig:
    """Return the whole connection, which is one address over the shipped defaults."""
    said = settings()
    auth = None
    if said.get("username"):
        auth = Credentials(said["username"], said.get("password", ""))
    return CameraConfig(
        host=host,
        port=int(said.get("port", 8080)),
        ssl=bool(said.get("ssl", False)),
        auth=auth,
        timeout=float(said.get("timeout", 5.0)),
        retries=int(said.get("retries", 3)),
        accepted_version=said.get("accepted_version"),
    )


# ── Which camera ─────────────────────────────────────────────────────────────


def named_host(host: str) -> str | None:
    """Return the address an operator chose, or None where they left it open."""
    return None if host == AUTO else host


def settle(host: str) -> str:
    """Return the one address to use, refusing rather than guessing between several."""
    chosen = named_host(host)
    if chosen is not None:
        return chosen
    found = probe.search()
    if len(found) == 1:
        return found[0].host
    if not found:
        pinned = pinned_host()
        if pinned:
            return pinned
        raise probe.NoCameraError(
            "nothing answered a discovery search, and no address is configured"
        )
    raise probe.NoCameraError(
        f"{len(found)} cameras answered; name the one to use: "
        + ", ".join(one.host for one in found)
    )


# ── The camera ───────────────────────────────────────────────────────────────


def state() -> SubsystemState:
    """Return whether the camera is reachable, which is what having a link says."""
    if _camera is not None and _camera.link.state is LinkState.UP:
        return SubsystemState.UP
    return SubsystemState.ERROR if _failure else SubsystemState.DOWN


def camera() -> Camera:
    """Return the connected camera, or say there is nothing to call through."""
    if _camera is None:
        raise probe.NotConnected("the camera is not connected")
    return _camera


def open_link(host: str, transport: Any = None) -> str:
    """Connect, atomically, so a half-open camera is not representable.

    A transport may be handed in, which is how everything above here is exercised
    with no camera on the network.
    """
    global _camera, _failure
    chosen = settle(host)
    opened = Camera(configured(chosen), transport)
    try:
        opened.connect()
    except Exception as exc:
        _failure = f"{type(exc).__name__}: {exc}"
        log.warning("could not connect to {}: {}", chosen, exc)
        raise
    _failure = None
    _camera = opened
    return chosen


def close_link() -> None:
    """Disconnect and forget, whatever state it was in."""
    global _camera, _failure
    open_now, _camera = _camera, None
    _failure = None
    if open_now is not None:
        open_now.disconnect()
