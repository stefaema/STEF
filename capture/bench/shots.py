"""Taking frames, the several ways the protocol offers, and what each leaves behind."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from portable.ccapi import DeviceBusyError, PollWait
from shared.diagnostics import Failed, Test, end, step
from shared.subsystem import Level, Result, Table, integer

if TYPE_CHECKING:
    from capture.subsystem import Capture

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


class Captures(Test[Any]):
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

    sub: Capture

    @step("In one call", hazard="releases the shutter")
    def in_one_call(self) -> None:
        found = self.sub.camera()
        self.made: list[str] = []
        self.rows: list[tuple[str, ...]] = []
        found.events.poll(PollWait.IMMEDIATELY)
        started = time.monotonic()
        found.shooting.capture(af=False)
        paths = landed(found)
        self.made.extend(paths)
        self.rows.append(
            ("in one call", f"{time.monotonic() - started:.2f} s", str(len(paths)))
        )
        if not paths:
            raise Failed("the one-call release announced nothing")
        self.report(f"{len(paths)} file(s)")

    @step("A press at a time", hazard="holds and releases the shutter")
    def a_press_at_a_time(self) -> None:
        found = self.sub.camera()
        found.events.poll(PollWait.IMMEDIATELY)
        started = time.monotonic()
        with found.shooting.held(af=False) as button:
            button.press()
        paths = landed(found)
        self.made.extend(paths)
        self.rows.append(
            (
                "a press at a time",
                f"{time.monotonic() - started:.2f} s",
                str(len(paths)),
            )
        )
        if not paths:
            raise Failed("the manual release announced nothing")
        self.report(f"{len(paths)} file(s)")

    @end("Clean up")
    def clean_up(self) -> None:
        made = getattr(self, "made", [])
        removed = swept(self.sub.camera(), tuple(made))
        clean = removed == len(made)
        said = self.report if clean else self.warn
        said(
            f"{removed} of {len(made)} removed",
            Result(
                level=Level.OK if clean else Level.WARN,
                summary=f"both ways took a frame; {removed} of {len(made)} removed",
                note=None if clean else "the rest are still on the card",
                table=Table(
                    head=("Release", "Took", "Files"),
                    rows=tuple(getattr(self, "rows", [])),
                ),
            ),
        )


# ── How fast it will actually go ─────────────────────────────────────────────


class FrameRate(Test[Any]):
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

    sub: Capture
    inputs = (
        integer(
            "seconds",
            unit="s",
            min=1,
            max=120,
            hint="How long to keep firing. The run stops on the clock, not a count.",
        ),
        integer(
            "busy wait",
            unit="ms",
            min=0,
            max=2_000,
            hint="When the body refuses, how long to lose before asking again.",
        ),
    )

    @step("Fire", hazard="releases the shutter as fast as the body allows")
    def fire(self) -> None:
        found = self.sub.camera()
        self.seconds = seconds = int(self.values.get("seconds", 10))
        waiting = int(self.values.get("busy wait", 20)) / 1000.0

        self.before = found.filesystem.file_count
        self.thermal_before = found.status.thermal()
        found.events.poll(PollWait.IMMEDIATELY)

        self.accepted = accepted = 0
        self.refused = refused = 0
        self.lost = lost = 0.0
        started = time.monotonic()
        deadline = started + seconds
        with found.link.retrying(retries=0):
            while time.monotonic() < deadline and accepted < MOST_FRAMES:
                self.checkpoint()
                try:
                    found.shooting.capture(af=False)
                    accepted += 1
                except DeviceBusyError:
                    refused += 1
                    lost += waiting
                    time.sleep(waiting)
                except Exception:  # noqa: BLE001
                    refused += 1
        self.accepted, self.refused, self.lost = accepted, refused, lost
        self.firing = time.monotonic() - started
        self.capped = capped = accepted >= MOST_FRAMES
        said = self.warn if capped else self.report
        said(
            f"{accepted} accepted, {refused} refused"
            + (f", stopped at {MOST_FRAMES}" if capped else "")
        )

    @step("Measure")
    def measure_rate(self) -> None:
        found = self.sub.camera()
        time.sleep(SETTLE)
        self.written = written = found.filesystem.file_count - self.before
        thermal_after = found.status.thermal()
        firing, accepted, capped = self.firing, self.accepted, self.capped
        achieved = written / firing if firing else 0.0
        honest = written >= accepted and not capped

        self.measure("achieved", round(achieved, 2), unit="frames/s")
        said = self.report if honest else self.warn
        said(
            f"{achieved:.2f} frames/s",
            Result(
                level=Level.OK if honest else Level.WARN,
                summary=f"{achieved:.2f} frames/s",
                note=(
                    f"stopped at {MOST_FRAMES} frames with {self.seconds - firing:.0f} s left; "
                    "this body is faster than this routine is built to measure"
                    if capped
                    else None
                    if honest
                    else f"{accepted - written} accepted release(s) never landed a file"
                ),
                fields=(
                    ("achieved", f"{achieved:.2f} frames/s"),
                    (
                        "per frame",
                        f"{firing / written * 1000:.0f} ms" if written else "--",
                    ),
                    ("landed", str(written)),
                    ("accepted", str(accepted)),
                    ("refused", str(self.refused)),
                    ("waited on refusals", f"{self.lost:.1f} s of {firing:.1f} s"),
                    ("thermal before", self.thermal_before.name),
                    ("thermal after", thermal_after.name),
                ),
            ),
        )

    @end("Clean up")
    def clean_up(self) -> None:
        found = self.sub.camera()
        if not hasattr(self, "before"):
            self.report("nothing was fired")
            return
        written = found.filesystem.file_count - self.before
        made = found.filesystem.files_in(found.filesystem.current_directory())
        removed = swept(found, made[-written:] if written > 0 else ())
        self.report(f"{removed} removed")


# ── Movie, briefly ───────────────────────────────────────────────────────────


class Records(Test[Any]):
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

    sub: Capture

    @step("Enter movie mode", hazard="switches the body into movie mode")
    def enter_movie_mode(self) -> None:
        found = self.sub.camera()
        found.events.poll(PollWait.IMMEDIATELY)
        mode = found.movie.mode()
        mode.__enter__()
        self.mode: Any = mode
        self.report("in movie mode")

    @step("Record", hazard="records a movie")
    def record(self) -> None:
        with self.sub.camera().movie.recording():
            time.sleep(RECORDING)
        self.report(f"recorded {RECORDING:.0f} s")

    @step("Leave")
    def leave(self) -> None:
        mode, self.mode = self.mode, None
        mode.__exit__(None, None, None)
        if self.sub.camera().movie.in_movie_mode():
            raise Failed("still in movie mode")
        self.report("back in stills mode")

    @end("Clean up")
    def clean_up(self) -> None:
        found = self.sub.camera()
        mode = getattr(self, "mode", None)
        if mode is not None:
            self.mode = None
            mode.__exit__(None, None, None)
        paths = landed(found)
        removed = swept(found, paths)
        said = self.report if paths else self.warn
        said(f"{removed} removed" if paths else "nothing was announced to remove")
