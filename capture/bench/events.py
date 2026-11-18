"""Being told what changed, the two ways, and what each costs."""

import time
from typing import TYPE_CHECKING, Any

from portable.ccapi import PollWait
from shared.diagnostics import Test, end, step
from shared.subsystem import Level, Result, Table, integer

if TYPE_CHECKING:
    from capture.subsystem import Capture


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


class HowLongAPollWaits(Test[Any]):
    """Time each of the three waits a poll may be asked for.

    `immediately` answers now, `short` and `long` hold the connection until
    something happens or the camera gives up. Knowing what each costs when
    nothing is happening is what makes one of them the right one for a loop.
    """

    sub: Capture

    def _timed(self, wait: PollWait) -> None:
        timings = self.__dict__.setdefault("timings", [])
        started = time.monotonic()
        change = self.sub.camera().events.poll(wait)
        elapsed = time.monotonic() - started
        timings.append(
            (wait.value, f"{elapsed:.2f} s", "yes" if change.empty else "no")
        )
        self.measure(wait.value, round(elapsed, 2), unit="s")
        self.report(f"{wait.value}: {elapsed:.2f} s")

    @step("Immediately")
    def immediately(self) -> None:
        self._timed(PollWait.IMMEDIATELY)

    @step("Short")
    def short(self) -> None:
        self._timed(PollWait.SHORT)

    @step("Long")
    def long(self) -> None:
        self._timed(PollWait.LONG)

    @step("Compare")
    def compare(self) -> None:
        self.report(
            "timed",
            Result(
                level=Level.OK,
                summary="what each wait costs with nothing happening",
                table=Table(
                    head=("Wait", "Took", "Empty"), rows=tuple(self.__dict__["timings"])
                ),
            ),
        )


class WatchForAWhile(Test[Any]):
    """Hold the push stream open and see what arrives unprompted.

    Nothing may arrive, and that is an answer: it means the camera is idle
    rather than that the stream is broken. Turning a dial on the body while this
    runs is how you prove it is not.
    """

    sub: Capture
    inputs = (integer("seconds", unit="s", min=1, max=60),)

    @step("Open")
    def open(self) -> None:
        self.seconds = int(self.values.get("seconds", 5))
        self.changes: list[Any] = []
        self.watching = self.sub.camera().events.watching()
        self.feed = self.watching.__enter__()
        self.report("stream open")

    @step("Listen")
    def listen(self) -> None:
        deadline = time.monotonic() + self.seconds
        for change in self.feed:
            self.changes.append(change)
            if time.monotonic() > deadline:
                break
        self.report(f"{len(self.changes)} change(s)")

    @end("Close")
    def close(self) -> None:
        watching = getattr(self, "watching", None)
        if watching is not None:
            watching.__exit__(None, None, None)
        changes = getattr(self, "changes", [])
        rows = tuple(row for change in changes for row in described(change))
        said = self.report if changes else self.warn
        said(
            f"{len(changes)} change(s) in {getattr(self, 'seconds', 0)}s",
            Result(
                level=Level.OK if changes else Level.WARN,
                summary=f"{len(changes)} change(s) while watching",
                note=None
                if changes
                else "nothing happened; turn a dial and run it again",
                table=Table(head=("Field", "Value"), rows=rows) if rows else None,
            ),
        )
