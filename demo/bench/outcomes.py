from __future__ import annotations

from typing import TYPE_CHECKING, Any

from demo.bench.link import pause
from shared.diagnostics import FAILED, Failed, Test, end, step
from shared.subsystem import READY, Level, Readiness, Result, Table, blocked

if TYPE_CHECKING:
    from demo.subsystem import Demo


class Passes(Test[Any]):
    """Pass every step.

    Three steps that each report a detail, and one that attaches a result.
    """

    sub: Demo

    @step("Greet")
    def greet(self) -> None:
        pause()
        self.report("the demo board answered")

    @step("Read")
    def read(self) -> None:
        pause()
        celsius = self.sub.board().temperature()
        self.report(
            f"{celsius} C",
            Result(
                level=Level.OK,
                summary=f"the board is at {celsius} C",
                fields=(("temperature", f"{celsius} C"),),
                table=Table(
                    head=("drive", "enabled", "velocity"),
                    rows=tuple(
                        (name, "yes" if one.enabled else "no", str(one.velocity))
                        for name, one in self.sub.board().drives.items()
                    ),
                ),
            ),
        )

    @step("Measure")
    def measure_it(self) -> None:
        pause()
        self.measure(
            "temperature", self.sub.board().temperature(), unit="C", low=0, high=60
        )
        self.report("inside its limits")


class Warns(Test[Any]):
    """Pass with a warning."""

    sub: Demo

    @step("Look")
    def look(self) -> None:
        pause()
        self.report("all quiet")

    @step("Notice")
    def notice(self) -> None:
        pause()
        self.warn(
            "something is worth a second look",
            Result(level=Level.WARN, summary="a warning, which is not a failure"),
        )


class FailsEarly(Test[Any]):
    """Fail on the first step.

    Every step after it is shown as not reached.
    """

    sub: Demo

    @step("Break")
    def break_it(self) -> None:
        pause()
        raise Failed(
            "the demo board failed this step, as asked",
            Result(level=Level.ERROR, summary="a failure with a result attached"),
        )

    @step("Never")
    def never(self) -> None:
        pass

    @step("Not this either")
    def not_this_either(self) -> None:
        pass


class CarriesOn(Test[Any]):
    """Fail one step and run the next anyway."""

    sub: Demo

    @step("Break", continue_on_failure=True)
    def break_it(self) -> None:
        pause()
        raise RuntimeError("an exception becomes the detail")

    @step("Keep going")
    def keep_going(self) -> None:
        pause()
        self.report("ran despite the failure before it")


class OutOfLimits(Test[Any]):
    """Measure something outside its limits."""

    sub: Demo

    @step("Measure")
    def measure_it(self) -> None:
        pause()
        self.measure("temperature", self.sub.board().temperature(), unit="C", high=10)
        self.measure("drives", len(self.sub.board().drives), expected=2)


class FinishesEarly(Test[Any]):
    """Find nothing left to do and stop early."""

    sub: Demo

    @step("Look")
    def look(self) -> None:
        pause()
        self.finish("already done, so the rest is not needed")

    @step("Do it", skippable=True)
    def do_it(self) -> None:
        pass


class SkipsOne(Test[Any]):
    """Skip one step and run the next."""

    sub: Demo

    @step("Maybe")
    def maybe(self) -> None:
        pause()
        self.skip("not on this board")

    @step("Always")
    def always(self) -> None:
        pause()
        self.report("ran")


class EndsBadly(Test[Any]):
    """Pass, then fail to put the board back.

    An error in the end step is the worst verdict, because the hardware may
    still be on.
    """

    sub: Demo

    @step("Work")
    def work(self) -> None:
        pause()
        self.report("done")

    @end("Put it back")
    def put_it_back(self) -> None:
        pause()
        raise TimeoutError("the demo board did not confirm, as asked")


class Guarded(Test[Any]):
    """Run only while the left drive is enabled.

    Enable it with the enable command, and this test becomes runnable.
    """

    sub: Demo

    @classmethod
    def can_run(cls, sub: Any) -> Readiness:
        if not sub.board().drive("left").enabled:
            return blocked("enable the left drive first")
        return READY

    @step("Check")
    def check(self) -> None:
        pause()
        if not self.sub.board().drive("left").enabled:
            self.finish("the left drive was disabled meanwhile", FAILED)
        self.report("the left drive is enabled")
