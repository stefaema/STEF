"""Taking frames, the several ways the protocol offers, and what each leaves behind."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from capture import capture
from portable.ccapi import DeviceBusyError, PollWait
from shared import bench_api
from shared.bench_api import (
    FAILED,
    PASSED,
    SETUP,
    WARNED,
    Abandoned,
    Level,
    Result,
    StepOutcome,
    Table,
)

SETTLE = 8.0
MOST_FRAMES = 500
RECORDING = 5.0


def landed(found: Any, timeout: float = SETTLE) -> tuple[str, ...]:
    """Return the files that appeared, waiting only as long as one may take to write."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        change = found.events.poll(PollWait.SHORT)
        seen.extend(change.added)
        if seen:
            break
    return tuple(seen)


def swept(found: Any, paths: tuple[str, ...]) -> int:
    """Delete what a routine made, so running it twice costs nothing."""
    gone = 0
    for path in paths:
        try:
            found.filesystem.discard(path)
            gone += 1
        except Exception:  # noqa: BLE001
            pass
    return gone


# ── One frame, the two ways the protocol offers ──────────────────────────────


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["In one call", "A press at a time", "Clean up"],
)
def captures(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Take a frame each way the protocol offers and confirm each by what it announced.

    The one-call endpoint presses, exposes and lets go by itself, so nothing can
    be left held; it is what a scan uses. The manual endpoint is the only way to
    hold the button down, which means it is also the only one that can strand a
    body with the shutter half pressed, so releasing is guaranteed however this
    ends.

    Neither drives the lens. The film plane does not move between frames, so a
    servo hunting is time spent and a frame risked, and focus is set once by
    hand before a reel rather than per release.

    Confirmation is the `added` path off the event stream rather than a file
    count, because that is what a scan will listen to.
    """
    found = capture.camera()
    made: list[str] = []
    rows: list[tuple[str, ...]] = []

    found.events.poll(PollWait.IMMEDIATELY)
    started = time.monotonic()
    found.shooting.capture(af=False)
    paths = landed(found)
    made.extend(paths)
    rows.append(("in one call", f"{time.monotonic() - started:.2f} s", str(len(paths))))
    if not paths:
        raise Abandoned("the one-call release announced nothing", FAILED)
    yield StepOutcome(PASSED, f"{len(paths)} file(s)")

    found.events.poll(PollWait.IMMEDIATELY)
    started = time.monotonic()
    with found.shooting.held(af=False) as button:
        button.press()
    paths = landed(found)
    made.extend(paths)
    rows.append(
        ("a press at a time", f"{time.monotonic() - started:.2f} s", str(len(paths)))
    )
    if not paths:
        raise Abandoned("the manual release announced nothing", FAILED)
    yield StepOutcome(PASSED, f"{len(paths)} file(s)")

    removed = swept(found, tuple(made))
    clean = removed == len(made)
    yield StepOutcome(
        PASSED if clean else WARNED,
        f"{removed} of {len(made)} removed",
        Result(
            level=Level.OK if clean else Level.WARN,
            summary=f"both ways took a frame; {removed} of {len(made)} removed",
            note=None if clean else "the rest are still on the card",
            table=Table(head=("Release", "Took", "Files"), rows=tuple(rows)),
        ),
    )


# ── How fast it will actually go ─────────────────────────────────────────────


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Fire", "Measure", "Clean up"],
    inputs=[
        bench_api.integer(
            "seconds",
            unit="s",
            min=1,
            max=120,
            hint="How long to keep firing. The run stops on the clock, not a count.",
        ),
        bench_api.integer(
            "busy wait",
            unit="ms",
            min=0,
            max=2_000,
            hint="When the body refuses, how long to lose before asking again.",
        ),
    ],
)
def frame_rate(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Fire as fast as the body will accept and report the rate that came out.

    Nothing here paces the shutter. The camera sets the rate by refusing what it
    cannot take yet, and the only thing under our control is how long we wait
    after each refusal, which is the one input. A short wait asks the body
    again the moment it might be ready and costs a great many refusals to find
    out; a long one asks rarely and leaves the body idle between frames. The
    rate this returns is what the two, together, actually achieved.

    The run ends on the clock. A count would end on the last frame, which is a
    promise a stalled call cannot keep. A ceiling of `MOST_FRAMES` sits behind
    the clock so a body far faster than this transport cannot fill a card while
    being measured; reaching it warns rather than passes, because the rate then
    describes the ceiling and not the camera.
    """
    found = capture.camera()
    seconds = int(values.get("seconds", 10))
    waiting = int(values.get("busy wait", 20)) / 1000.0

    before = found.filesystem.file_count
    thermal_before = found.status.thermal()
    found.events.poll(PollWait.IMMEDIATELY)

    accepted = 0
    refused = 0
    lost = 0.0
    started = time.monotonic()
    deadline = started + seconds
    with found.link.retrying(retries=0):
        while time.monotonic() < deadline and accepted < MOST_FRAMES:
            try:
                found.shooting.capture(af=False)
                accepted += 1
            except DeviceBusyError:
                refused += 1
                lost += waiting
                time.sleep(waiting)
            except Exception:  # noqa: BLE001
                refused += 1
    firing = time.monotonic() - started
    capped = accepted >= MOST_FRAMES
    yield StepOutcome(
        WARNED if capped else PASSED,
        f"{accepted} accepted, {refused} refused"
        + (f", stopped at {MOST_FRAMES}" if capped else ""),
    )

    time.sleep(SETTLE)
    written = found.filesystem.file_count - before
    thermal_after = found.status.thermal()
    achieved = written / firing if firing else 0.0
    honest = written >= accepted and not capped

    yield StepOutcome(
        PASSED if honest else WARNED,
        f"{achieved:.2f} frames/s",
        Result(
            level=Level.OK if honest else Level.WARN,
            summary=f"{achieved:.2f} frames/s",
            note=(
                f"stopped at {MOST_FRAMES} frames with {seconds - firing:.0f} s left; "
                "this body is faster than this routine is built to measure"
                if capped
                else None
                if honest
                else f"{accepted - written} accepted release(s) never landed a file"
            ),
            fields=(
                ("achieved", f"{achieved:.2f} frames/s"),
                ("per frame", f"{firing / written * 1000:.0f} ms" if written else "--"),
                ("landed", str(written)),
                ("accepted", str(accepted)),
                ("refused", str(refused)),
                ("waited on refusals", f"{lost:.1f} s of {firing:.1f} s"),
                ("thermal before", thermal_before.name),
                ("thermal after", thermal_after.name),
            ),
        ),
    )

    made = found.filesystem.files_in(found.filesystem.current_directory())
    removed = swept(found, made[-written:] if written else ())
    yield StepOutcome(PASSED, f"{removed} removed")


# ── Movie, briefly ───────────────────────────────────────────────────────────


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Enter movie mode", "Record", "Leave", "Clean up"],
)
def records(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Record for `RECORDING` seconds and throw the result away.

    Not because a telecine wants video, but because movie mode and the
    recording inside it are two nested states the camera holds, and a block
    that leaves either one on is a camera nothing else can use. Entering is the
    part that fails: the camera acknowledges the request before the mode has
    physically taken effect, so `mode()` waits for the readback rather than
    trusting the acknowledgement.

    The length is fixed. Nothing here measures duration, so a knob would only
    offer a way to wait longer for the same answer.
    """
    found = capture.camera()
    found.events.poll(PollWait.IMMEDIATELY)

    with found.movie.mode():
        yield StepOutcome(PASSED, "in movie mode")
        with found.movie.recording():
            time.sleep(RECORDING)
        yield StepOutcome(PASSED, f"recorded {RECORDING:.0f} s")

    settled = not found.movie.in_movie_mode()
    yield StepOutcome(
        PASSED if settled else FAILED,
        "back in stills mode" if settled else "still in movie mode",
    )

    paths = landed(found)
    removed = swept(found, paths)
    yield StepOutcome(
        PASSED if paths else WARNED,
        f"{removed} removed" if paths else "nothing was announced to remove",
    )
