"""Heating, the several ways a test can end."""

import threading
from typing import Any

from shared.diagnostics import FAILED, Needs, Test, end, step
from shared.subsystem import blocked, boolean, confirmation, integer

CELSIUS = integer("celsius", unit="C", max=300)


class Preheat(Test[Any]):
    """Preheat the oven.

    Writes one setpoint and waits for the probe to agree with it.
    """

    inputs = (CELSIUS,)

    @step("Write setpoint", hazard="switches the element on")
    def write(self) -> None:
        self.sub.handle().set_point(self.values["celsius"])
        self.report(f"asked for {self.values['celsius']} C")

    @step("Wait for the probe")
    def wait(self) -> None:
        target = self.values["celsius"]
        self.measure(
            "probe",
            self.sub.handle().reading() + self.sub.drift,
            unit="C",
            low=target - 5,
            high=target + 5,
        )

    @end("Element off")
    def element_off(self) -> None:
        self.sub.handle().set_point(0)


class Breaks(Test[Any]):
    """Break on the first step."""

    @step("First")
    def first(self) -> None:
        raise RuntimeError("the element is open circuit")

    @step("Second")
    def second(self) -> None:
        pass

    @end("Off")
    def off(self) -> None:
        self.sub.handle().set_point(0)


class Carries(Test[Any]):
    """Fail one step and carry on."""

    @step("First", continue_on_failure=True)
    def first(self) -> None:
        raise RuntimeError("worth knowing")

    @step("Second")
    def second(self) -> None:
        self.warn("a little slow")


class Finishes(Test[Any]):
    """End as soon as there is nothing left to do."""

    @step("Look")
    def look(self) -> None:
        self.finish("already hot")

    @step("Heat", skippable=True)
    def heat(self) -> None:
        raise AssertionError("never reached")


class Skips(Test[Any]):
    """Skip one step only."""

    @step("Maybe")
    def maybe(self) -> None:
        self.skip("not on this model")

    @step("Always")
    def always(self) -> None:
        self.report("ran")


class EndsBadly(Test[Any]):
    """Leave the element in doubt."""

    @step("Heat")
    def heat(self) -> None:
        pass

    @end("Off")
    def off(self) -> None:
        raise TimeoutError("the element did not answer")


class Asks(Test[Any]):
    """Ask whether it smells."""

    smelled = boolean("smelled", hint="Can you smell burning?")
    ready = confirmation("Close the door, then press Continue.")

    @step("Close")
    def close(self) -> None:
        self.ask(self.ready)

    @step("Smell")
    def smell(self) -> None:
        if self.ask(self.smelled, timeout=self.sub.patience):
            self.warn("the operator smelled burning")


class Waits(Test[Any]):
    """Wait until told to stop."""

    started = threading.Event()

    @step("Wait")
    def wait(self) -> None:
        Waits.started.set()
        while True:
            self.checkpoint()

    @step("After")
    def after(self) -> None:
        pass

    @end("Off")
    def off(self) -> None:
        self.sub.handle().set_point(0)


class Unplugged(Test[Any]):
    """Ask the socket, which needs the link down."""

    needs = Needs.DOWN

    @step("Socket")
    def socket(self) -> None:
        pass


class Guarded(Test[Any]):
    """Run only on a cold element."""

    @classmethod
    def can_run(cls, sub: Any):
        return blocked("the element is hot")

    @step("Never")
    def never(self) -> None:
        pass


class ElementReady(Test[Any]):
    @step("Identify")
    def identify(self) -> None:
        pass

    @step("Element on", hazard="switches the element on")
    def element_on(self) -> None:
        self.sub.handle().set_point(100)

    @end("Element off")
    def element_off(self) -> None:
        self.sub.handle().set_point(0)


class Holds(ElementReady):
    """Hold a temperature."""

    @step("Hold")
    def hold(self) -> None:
        self.finish("held", FAILED)
