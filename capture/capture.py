"""Which camera this machine was told about, and how to settle on one."""

from __future__ import annotations

from typing import Any

from capture import probe
from portable.ccapi import CameraConfig, Credentials
from shared import config, logs

PACKAGE = "capture"
SETTINGS = f"camera{config.SUFFIX}"
AUTO = "auto"

log = logs.as_component("capture")


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
    swept = probe.sweep()
    found = swept.found
    if len(found) == 1:
        return found[0].host
    if not found:
        pinned = pinned_host()
        if pinned:
            return pinned
        raise probe.NoCameraError(f"{swept.sentence} No address is configured either.")
    raise probe.NoCameraError(
        f"{len(found)} cameras answered; name the one to use: "
        + ", ".join(one.host for one in found)
    )
