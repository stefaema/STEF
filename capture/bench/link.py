"""Opening and closing the camera, which is the one thing everything else waits on."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from capture import capture, probe
from shared import bench_api
from shared.bench_api import (
    LINK,
    PASSED,
    READY,
    Level,
    Readiness,
    Result,
    StepOutcome,
    blocked,
)

HOST = bench_api.choice(
    "host",
    capture.cameras,
    hint="Which camera. 'auto' when discovery finds exactly one.",
)


def camera_is_down() -> Readiness:
    """Say whether there is no camera yet, which is what connecting needs."""
    if capture.state() is bench_api.SubsystemState.UP:
        return blocked("already connected")
    return READY


def camera_is_up() -> Readiness:
    """Say whether there is a camera to disconnect from."""
    if capture.state() is bench_api.SubsystemState.UP:
        return READY
    return blocked("not connected")


def can_connect(host: str = capture.AUTO) -> Readiness:
    """Say whether this camera will serve us, and what is there when it will not.

    Only one device may hold a camera at a time, so this connects and lets go
    rather than leaving anything open behind it.
    """
    try:
        chosen = capture.settle(host)
    except probe.NoCameraError as exc:
        return blocked(str(exc))
    return probe.identify(capture.configured(chosen))


@bench_api.routine(
    category=LINK, inputs=[HOST], can_run=camera_is_down, can_run_with=can_connect
)
def connect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Connect.

    Reads the camera's manifest and nothing else, so the body is left in
    whatever mode it was already in.
    """
    chosen = capture.open_link(values.get("host", capture.AUTO))
    found = capture.camera()
    yield StepOutcome(
        PASSED,
        f"connected to {chosen}",
        Result(
            level=Level.OK,
            summary=f"connected to {chosen}",
            fields=(
                ("versions", ", ".join(found.link.registry.versions)),
                ("endpoints", str(len(found.link.registry.features))),
            ),
        ),
    )


@bench_api.routine(category=LINK, can_run=camera_is_up)
def disconnect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Disconnect.

    Lets go of the camera, which is what another device needs before it can
    have one.
    """
    capture.close_link()
    yield StepOutcome(PASSED, "disconnected")
