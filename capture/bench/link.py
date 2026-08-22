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
    Option,
    Readiness,
    Result,
    StepOutcome,
    blocked,
)


def cameras() -> tuple[Option, ...]:
    """Return every address worth trying, discovered first and pinned after.

    Discovery is multicast, so it does not cross a subnet and a switch may eat
    it. What it finds is a recommendation; the pinned address is the answer for
    a camera it cannot see.
    """
    found = probe.search()
    options = [Option(capture.AUTO, capture.AUTO)]
    options.extend(Option(one.host, one.label) for one in found)
    pinned = capture.pinned_host()
    if pinned and all(one.host != pinned for one in found):
        options.append(Option(pinned, f"{pinned} (configured)"))
    return tuple(options)


HOST = bench_api.choice(
    "host",
    cameras,
    hint="Which camera. 'auto' when discovery finds exactly one.",
)


def camera_is_down() -> Readiness:
    """Say whether there is no camera yet, which is what connecting needs."""
    if capture.link_state() is bench_api.SubsystemLinkState.UP:
        return blocked("already connected")
    return READY


def camera_is_up() -> Readiness:
    """Say whether there is a camera to disconnect from."""
    if capture.link_state() is bench_api.SubsystemLinkState.UP:
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
    verdict = probe.identify(capture.configured(chosen))
    return READY if verdict else blocked(verdict.sentence)


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
