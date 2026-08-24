"""Being told what changed, the two ways, and what each costs."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from capture import capture
from portable.ccapi import PollWait
from shared import bench_api
from shared.bench_api import (
    PASSED,
    SETUP,
    WARNED,
    Level,
    Result,
    StepOutcome,
    Table,
)


def described(change: Any) -> tuple[tuple[str, ...], ...]:
    """Return what one poll answered with, as rows a screen can read."""
    rows: list[tuple[str, ...]] = []
    for name in ("battery", "lens", "thermal", "storage"):
        found = getattr(change, name)
        if found is not None:
            rows.append((name, str(found)))
    for name, paths in (
        ("added", change.added),
        ("removed", change.removed),
        ("updated", change.updated),
    ):
        if paths:
            rows.append((name, ", ".join(paths)))
    if change.settings:
        rows.append(("settings", ", ".join(sorted(change.settings))))
    return tuple(rows)


@bench_api.routine(category=SETUP, steps=["Immediately", "Short", "Long"])
def how_long_a_poll_waits(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Time each of the three waits a poll may be asked for.

    `immediately` answers now, `short` and `long` hold the connection until
    something happens or the camera gives up. Knowing what each costs when
    nothing is happening is what makes one of them the right one for a loop.
    """
    found = capture.camera()
    timings = []
    for wait in (PollWait.IMMEDIATELY, PollWait.SHORT, PollWait.LONG):
        started = time.monotonic()
        change = found.events.poll(wait)
        elapsed = time.monotonic() - started
        timings.append(
            (wait.value, f"{elapsed:.2f} s", "yes" if change.empty else "no")
        )
        yield StepOutcome(PASSED, f"{wait.value}: {elapsed:.2f} s")
    yield StepOutcome(
        PASSED,
        "timed",
        Result(
            level=Level.OK,
            summary="what each wait costs with nothing happening",
            table=Table(head=("Wait", "Took", "Empty"), rows=tuple(timings)),
        ),
    )


@bench_api.routine(
    category=SETUP,
    steps=["Open", "Listen", "Close"],
    inputs=[bench_api.integer("seconds", unit="s", min=1, max=60)],
)
def watch_for_a_while(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Hold the push stream open and see what arrives unprompted.

    Nothing may arrive, and that is an answer: it means the camera is idle
    rather than that the stream is broken. Turning a dial on the body while this
    runs is how you prove it is not.
    """
    found = capture.camera()
    seconds = int(values.get("seconds", 5))
    changes: list[Any] = []
    with found.events.watching() as feed:
        yield StepOutcome(PASSED, "stream open")
        deadline = time.monotonic() + seconds
        for change in feed:
            changes.append(change)
            if time.monotonic() > deadline:
                break
        yield StepOutcome(PASSED, f"{len(changes)} change(s)")
    rows = tuple(row for change in changes for row in described(change))
    yield StepOutcome(
        PASSED if changes else WARNED,
        f"{len(changes)} change(s) in {seconds}s",
        Result(
            level=Level.OK if changes else Level.WARN,
            summary=f"{len(changes)} change(s) while watching",
            note=None if changes else "nothing happened; turn a dial and run it again",
            table=Table(head=("Field", "Value"), rows=rows) if rows else None,
        ),
    )
