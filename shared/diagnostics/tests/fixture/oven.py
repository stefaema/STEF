from typing import Any

from shared.diagnostics import Diagnosable
from shared.diagnostics.tests.fixture import calls, heat
from shared.diagnostics.tests.fixture.hardware import Element
from shared.subsystem import Linked, choice


class Oven(Linked[str], Diagnosable):
    safe_state = "element off"
    target = choice("port", lambda sub: ("/dev/oven0",))
    tests = (
        heat.Preheat,
        heat.Breaks,
        heat.Carries,
        heat.Finishes,
        heat.Skips,
        heat.EndsBadly,
        heat.Asks,
        heat.Waits,
        heat.Unplugged,
        heat.Guarded,
        heat.Holds,
    )
    commands = (calls.set_element, calls.broken)

    def __init__(self, package: Any) -> None:
        super().__init__(package)
        self.drift = 0
        self.patience = 120.0
        self.stopped = 0

    def _open(self, target: str) -> Element:
        return Element()

    def _close(self, handle: Element) -> None:
        pass

    def stop(self) -> None:
        self.stopped += 1
        self.handle().set_point(0)
        self.handle().sent.append("stop")
