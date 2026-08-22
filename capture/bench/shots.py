"""Taking frames, the several ways the protocol offers, and what each leaves behind."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from capture import capture
from portable.ccapi import PollWait, ShutterAction
from portable.ccapi.vocabulary import NO_FILE
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


# ── One frame, the two ways ──────────────────────────────────────────────────


@bench_api.routine(
    category=SETUP, hazardous=True, steps=["Fire", "Confirm", "Clean up"]
)
def one_frame(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Take one frame the way a scan does.

    The single-call endpoint: the camera presses, exposes and lets go by itself,
    so nothing can be left held.
    """
    found = capture.camera()
    found.events.poll(PollWait.IMMEDIATELY)
    started = time.monotonic()
    found.shooting.capture(af=False)
    yield StepOutcome(PASSED, "fired")

    paths = landed(found)
    elapsed = time.monotonic() - started
    if not paths:
        raise Abandoned("nothing landed within the wait", FAILED)
    yield StepOutcome(
        PASSED,
        f"{len(paths)} file(s)",
        Result(
            level=Level.OK,
            summary=f"{len(paths)} file(s) landed",
            fields=(("elapsed", f"{elapsed:.2f} s"), ("first", paths[0])),
        ),
    )
    yield StepOutcome(PASSED, f"{swept(found, paths)} removed")


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Half press", "Full press", "Confirm", "Clean up"],
)
def one_frame_by_hand(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Take one frame a press at a time.

    The same photograph through the manual endpoint, which is the only way to
    hold the button down. Releasing is guaranteed however this ends.
    """
    found = capture.camera()
    found.events.poll(PollWait.IMMEDIATELY)
    with found.shooting.held(af=False) as button:
        yield StepOutcome(PASSED, "held at half")
        button.press()
        yield StepOutcome(PASSED, "pressed fully")
    paths = landed(found)
    if not paths:
        raise Abandoned("nothing landed within the wait", FAILED)
    yield StepOutcome(PASSED, f"{len(paths)} file(s)")
    yield StepOutcome(PASSED, f"{swept(found, paths)} removed")


@bench_api.routine(
    category=SETUP, hazardous=True, steps=["Half press", "Release", "Look"]
)
def half_press_takes_nothing(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Check that pressing halfway and letting go takes no photograph.

    Everyone believes this because that is how a camera behaves in the hand.
    Nothing in the reference says it, and `held()` is built on it.
    """
    found = capture.camera()
    before = found.filesystem.file_count
    found.events.poll(PollWait.IMMEDIATELY)
    found.shooting.manual_shutter(ShutterAction.HALF_PRESS, af=False)
    yield StepOutcome(PASSED, "held at half")
    found.shooting.release()
    yield StepOutcome(PASSED, "released")

    time.sleep(1.0)
    after = found.filesystem.file_count
    made = after - before
    settled = made == 0
    summary = (
        "half press leaves no file, as assumed"
        if settled
        else f"half press wrote {made} file(s), which nothing here expected"
    )
    yield StepOutcome(
        PASSED if settled else FAILED,
        summary,
        Result(
            level=Level.OK if settled else Level.ERROR,
            summary=summary,
            fields=(("before", str(before)), ("after", str(after))),
        ),
    )


# ── What one release actually writes ─────────────────────────────────────────


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Read quality", "Set raw+jpeg", "Fire", "Count", "Put it back"],
)
def raw_and_jpeg_writes_two(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Check how many files one release writes when the camera is set to raw+jpeg.

    Everything that counts frames assumes one release is one file. If a body set
    to write both breaks that, a reel's reconciliation is wrong from the first
    frame, and the quality setting is not something a scan should discover.
    """
    found = capture.camera()
    was = found.settings.image_quality()
    yield StepOutcome(PASSED, f"quality is raw {was.raw!r}, jpeg {was.jpeg!r}")

    if not was.offers_two:
        raise Abandoned(
            "this body writes only one file per release: "
            f"raw {', '.join(was.raw_allowed) or '-'}; "
            f"jpeg {', '.join(was.jpeg_allowed) or '-'}"
        )
    raw = next(one for one in was.raw_allowed if one != NO_FILE)
    jpeg = next(one for one in was.jpeg_allowed if one != NO_FILE)
    found.settings.set_image_quality(raw, jpeg)
    yield StepOutcome(PASSED, f"set to raw {raw!r} and jpeg {jpeg!r}")

    try:
        found.events.poll(PollWait.IMMEDIATELY)
        found.shooting.capture(af=False)
        yield StepOutcome(PASSED, "fired")

        paths = landed(found)
        many = len(paths) > 1
        summary = f"one release wrote {len(paths)} file(s)"
        yield StepOutcome(
            WARNED if many else PASSED,
            summary,
            Result(
                level=Level.WARN if many else Level.OK,
                summary=summary,
                note=(
                    "so a frame count cannot be a file count while this is set"
                    if many
                    else "so a frame is a file even here"
                ),
                table=Table(head=("File",), rows=tuple((one,) for one in paths)),
            ),
        )
        swept(found, paths)
    finally:
        found.settings.set_image_quality(was.raw, was.jpeg)
    yield StepOutcome(PASSED, f"quality back to raw {was.raw!r}, jpeg {was.jpeg!r}")


# ── How fast it will actually go ─────────────────────────────────────────────


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Fire", "Measure", "Clean up"],
    inputs=[
        bench_api.integer("frames", min=1, max=200, hint="How many to take."),
        bench_api.integer(
            "interval",
            unit="ms",
            min=0,
            max=10_000,
            hint="How long to wait between one release and the next.",
        ),
    ],
)
def burst(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Fire a run of frames at a fixed interval and see what the camera keeps up with.

    Asking for an interval the body cannot hold is how you find the interval it
    can. What comes back is the achieved rate, not the requested one, and the
    gap between them is the practical ceiling on scanning speed.
    """
    found = capture.camera()
    frames = int(values.get("frames", 10))
    interval = int(values.get("interval", 500)) / 1000.0

    before = found.filesystem.file_count
    thermal_before = found.status.thermal()
    found.events.poll(PollWait.IMMEDIATELY)

    started = time.monotonic()
    refused = 0
    for shot in range(frames):
        due = started + shot * interval
        pause = due - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        try:
            found.shooting.capture(af=False)
        except Exception:  # noqa: BLE001
            refused += 1
    firing = time.monotonic() - started
    yield StepOutcome(PASSED, f"{frames - refused} of {frames} accepted")

    time.sleep(SETTLE)
    after = found.filesystem.file_count
    written = after - before
    thermal_after = found.status.thermal()
    asked = frames / (frames * interval) if interval else float("inf")
    achieved = written / firing if firing else 0.0
    kept_up = refused == 0 and written >= frames

    yield StepOutcome(
        PASSED if kept_up else WARNED,
        f"{achieved:.2f} frames/s",
        Result(
            level=Level.OK if kept_up else Level.WARN,
            summary=f"{written} frames in {firing:.2f} s, {achieved:.2f} frames/s",
            note=(
                None
                if kept_up
                else f"{refused} release(s) refused and {frames - written} never landed"
            ),
            fields=(
                (
                    "asked",
                    f"{asked:.2f} frames/s" if interval else "as fast as it takes",
                ),
                ("achieved", f"{achieved:.2f} frames/s"),
                ("interval asked", f"{interval * 1000:.0f} ms"),
                ("interval achieved", f"{firing / max(frames, 1) * 1000:.0f} ms"),
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
    inputs=[bench_api.integer("seconds", unit="s", min=1, max=30)],
)
def record_briefly(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Record a couple of seconds of video and throw it away.

    Not because a telecine wants video, but because movie mode and the recording
    inside it are two nested states the camera holds, and a block that leaves
    either one on is a camera nothing else can use.
    """
    found = capture.camera()
    seconds = int(values.get("seconds", 2))
    found.events.poll(PollWait.IMMEDIATELY)

    with found.movie.mode():
        yield StepOutcome(PASSED, "in movie mode")
        with found.movie.recording():
            time.sleep(seconds)
        yield StepOutcome(PASSED, f"recorded {seconds}s")

    settled = not found.movie.in_movie_mode()
    yield StepOutcome(
        PASSED if settled else FAILED,
        "back in stills mode" if settled else "still in movie mode",
    )
    paths = landed(found)
    yield StepOutcome(PASSED, f"{swept(found, paths)} removed")
