from __future__ import annotations

from typing import Any

from shared.diagnostics import command
from shared.subsystem import Level, Result, integer


@command(inputs=(integer("celsius"),), hazard="switches the element on or off")
def set_element(oven: Any, values: dict[str, Any]) -> Result:
    """Switch the element.

    Writes the setpoint and leaves it there.
    """
    oven.handle().set_point(values["celsius"])
    return Result(level=Level.OK, summary=f"set to {values['celsius']} C")


@command()
def broken(oven: Any, values: dict[str, Any]) -> Result:
    """Break."""
    raise OSError("no reply")
