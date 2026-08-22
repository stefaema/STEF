"""What Transport, Capture and Detection have in common."""

import enum
from typing import Any

# What a subsystem package is asked for its state by.
STATE_ATTRIBUTE = "state"


class SubsystemState(enum.Enum):
    """Whether one subsystem is reachable."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


def state_of(module: Any) -> SubsystemState:
    """Return the state a subsystem package reports, or DOWN where it reports none.

    Asked through the module rather than through a function captured at load, so
    a package that reports differently later is believed.
    """
    reported = getattr(module, STATE_ATTRIBUTE, None)
    return reported() if reported is not None else SubsystemState.DOWN


__all__ = ["STATE_ATTRIBUTE", "SubsystemState", "state_of"]
