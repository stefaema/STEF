"""Bringing a camera to the state a scan needs, once it is open."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from capture import capture
from portable.ccapi import Setting
from shared import bench_api
from shared.bench_api import (
    FAILED,
    PASSED,
    SETUP,
    WARNED,
    Level,
    Result,
    StepOutcome,
    Table,
)

# What a scan needs a body to be, and why, one line each.
#
#   drive        continuous turns one release into a burst
#   afoperation  servo refocuses between frames
#   shuttermode  a mechanical curtain shakes the rig during the exposure
RECIPE = {
    Setting.DRIVE: "single",
    Setting.AFOPERATION: "oneshot",
    Setting.SHUTTERMODE: "electronic",
}

# The shutter modes worth having, least mechanical movement first.
QUIETEST = ("electronic", "elec_1st_curtain", "mechanical")

AWAKE = "disable"
HEAD = ("Setting", "Was", "Asked", "Now")


@bench_api.routine(category=SETUP, hazardous=True, steps=["Read", "Write", "Verify"])
def prepare_for_scanning(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Put the camera in the state a scan needs.

    Every one of these is a way to lose a frame rather than a preference, and a
    body arrives from the shop set for photography.
    """
    found = capture.camera()
    before = {}
    for setting in RECIPE:
        if not found.settings.offers(setting):
            continue
        before[setting] = found.settings.get(setting).value
    yield StepOutcome(PASSED, f"{len(before)} of {len(RECIPE)} offered")

    asked = {setting: RECIPE[setting] for setting in before}
    for setting, value in asked.items():
        allowed = found.settings.allowed(setting)
        if allowed and value not in allowed:
            value = next((one for one in QUIETEST if one in allowed), value)
            asked[setting] = value
        found.settings.set(setting, value)
    yield StepOutcome(PASSED, f"{len(asked)} written")

    rows = []
    disagreed = 0
    for setting, value in asked.items():
        now = found.settings.get(setting).value
        rows.append((str(setting), str(before[setting]), str(value), str(now)))
        if now != value:
            disagreed += 1
    status = WARNED if disagreed else PASSED
    level = Level.WARN if disagreed else Level.OK
    summary = (
        f"{disagreed} setting(s) did not take"
        if disagreed
        else "the camera is set for scanning"
    )
    yield StepOutcome(
        status,
        summary,
        Result(level=level, summary=summary, table=Table(head=HEAD, rows=tuple(rows))),
    )


@bench_api.routine(category=SETUP, hazardous=True, steps=["Read", "Write"])
def keep_awake(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Stop the camera going to sleep.

    A body that dozes off mid-reel looks exactly like a network fault, and the
    reel is a pass through film you do not get back.
    """
    found = capture.camera()
    was = found.functions.auto_power_off()
    yield StepOutcome(PASSED, f"auto power-off is {was!r}")
    if was == AWAKE:
        yield StepOutcome(PASSED, "already disabled")
        return
    found.functions.set_auto_power_off(AWAKE)
    now = found.functions.auto_power_off()
    settled = now == AWAKE
    yield StepOutcome(
        PASSED if settled else FAILED,
        f"auto power-off is now {now!r}",
        Result(
            level=Level.OK if settled else Level.ERROR,
            summary=f"was {was!r}, now {now!r}",
        ),
    )
