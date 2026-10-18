from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from demo.bench.link import pause
from shared.diagnostics import Failed, Test, end, step
from shared.subsystem import integer

if TYPE_CHECKING:
    from demo.subsystem import Demo


class RunsLong(Test[Any]):
    """Run until the time is up, or until it is cancelled.

    Try Stop while it runs: the step warns that it was cancelled, the rest is
    skipped, and the end step still runs.
    """

    sub: Demo
    inputs = (integer("seconds", unit="s", min=1, max=600, hint="How long to run."),)

    @step("Wait")
    def wait(self) -> None:
        seconds = int(self.values.get("seconds") or 30)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.checkpoint()
            time.sleep(0.1)
        self.report(f"waited {seconds} s")

    @step("After")
    def after(self) -> None:
        pause()
        self.report("reached")

    @end("Tidy up")
    def tidy_up(self) -> None:
        pause()
        self.report("tidied up, however the run ended")


class Hazardous(Test[Any]):
    """Turn a demo drive and leave it at rest.

    The two middle steps carry a hazard. The end step disables the drive and
    reads it back, however the run ended.
    """

    sub: Demo
    inputs = (
        integer("velocity", min=0, max=20_000, hint="How fast the demo drive turns."),
    )

    @step("Enable", hazard="energises the left demo drive")
    def enable(self) -> None:
        pause()
        self.sub.board().drive("left").enabled = True
        self.report("left drive enabled")

    @step("Turn", hazard="turns the left demo drive")
    def turn(self) -> None:
        velocity = int(self.values.get("velocity") or 5_000)
        self.sub.board().drive("left").velocity = velocity
        pause(3)
        self.measure("velocity", self.sub.board().drive("left").velocity, low=1)
        self.report(f"turned at {velocity}")

    @end("At rest")
    def at_rest(self) -> None:
        pause()
        drive = self.sub.board().drive("left")
        if drive.jammed:
            raise Failed("the left drive is jammed and did not stop")
        drive.velocity = 0
        drive.enabled = False
        self.measure("velocity", drive.velocity, expected=0)
        self.report("standing still, disabled")
