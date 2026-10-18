from __future__ import annotations

from typing import TYPE_CHECKING, Any

from demo.bench.link import pause
from shared.diagnostics import Needs, Test, step

if TYPE_CHECKING:
    from demo.subsystem import Demo


class NeedsThePort(Test[Any]):
    """Flash the demo board, which needs the link down.

    Shown under Before connecting, and refused while the link holds the port.
    """

    sub: Demo
    needs = Needs.DOWN

    @step("Erase", hazard="erases the demo board")
    def erase(self) -> None:
        pause(2)
        self.report("erased")

    @step("Write", hazard="writes the demo board")
    def write(self) -> None:
        pause(3)
        self.report("written")

    @step("Read back")
    def read_back(self) -> None:
        pause()
        self.report("reads back as written")
