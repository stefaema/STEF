from typing import Any

from shared.diagnostics import Needs, Test, step


class Warm(Test[Any]):
    """Warm the element."""

    needs = Needs.DOWN

    @step("Warming")
    def warming(self) -> None:
        self.report("warm")
