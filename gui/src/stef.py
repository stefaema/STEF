"""What the whole machine is doing, until the orchestrator exists to say so.

Temporary. It belongs to whatever coordinates the three subsystems, which is the
orchestrator, which is not designed yet. One file to delete and one call site to
repoint. Each subsystem's own state is its package's answer, not this one's.
"""

import enum
from dataclasses import dataclass


class StefState(enum.Enum):
    """What the machine as a whole is doing."""

    IDLE = "idle"
    BENCHING = "benching"
    SCANNING = "scanning"


@dataclass
class Stef:
    """The accessor the GUI reads gating from."""

    state: StefState = StefState.IDLE


STEF = Stef()
