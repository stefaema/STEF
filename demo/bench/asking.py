from typing import TYPE_CHECKING, Any

from demo.bench.link import pause
from shared.diagnostics import Failed, Test, step
from shared.subsystem import boolean, choice, confirmation

if TYPE_CHECKING:
    from demo.subsystem import Demo

COLOURS = ("red", "green", "blue")
PATIENCE_S = 15.0


class Asks(Test[Any]):
    """Ask the operator four questions.

    A confirmation, a yes or no, a choice, and one that cancels the run if nobody
    answers it in time.
    """

    sub: Demo
    ready = confirmation("Pretend to thread the film, then press Continue.")
    lit = boolean("lit", hint="Is the demo board's light on?")
    colour = choice("colour", COLOURS, hint="Which colour is the light?")
    hurry = boolean(
        "hurry", hint=f"Answer within {PATIENCE_S:.0f} s, or the run is cancelled."
    )

    @step("Confirm")
    def confirm(self) -> None:
        self.ask(self.ready)
        self.report("the operator confirmed")

    @step("Yes or no")
    def yes_or_no(self) -> None:
        if not self.ask(self.lit):
            raise Failed("the operator saw no light")
        self.report("the operator saw the light")

    @step("Choose")
    def choose(self) -> None:
        said = self.ask(self.colour)
        pause()
        self.report(f"the operator chose {said}")

    @step("In time")
    def in_time(self) -> None:
        self.ask(self.hurry, timeout=PATIENCE_S)
        self.report("answered in time")
