"""A hotplate on a dial, which is subsystem enough to assemble.

One element, one dial, and nothing to plug in.
"""

from typing import Any

from machine.tests.fixture import routines
from shared.diagnostics import Diagnosable
from shared.subsystem import Linked, choice


class Hotplate(Linked[str], Diagnosable):
    target = choice("dial", ("low", "high"))
    tests = (routines.Warm,)

    def _open(self, target: str) -> Any:
        return target

    def _close(self, handle: Any) -> None:
        pass


SUBSYSTEM = Hotplate
