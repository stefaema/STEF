"""What the whole machine is doing, until the orchestrator exists to say so.

Temporary. It belongs to whatever coordinates the three subsystems, which is the
orchestrator, which is not designed yet. `bench_api` never imports this; the GUI
reads it in one place, so it is one file to delete and one call site to repoint.
"""

import enum
from dataclasses import dataclass, field

from shared.bench_api.state import SubsystemState


class StefState(enum.Enum):
    """What the machine as a whole is doing."""

    IDLE = "idle"
    BENCHING = "benching"
    SCANNING = "scanning"


@dataclass
class SubsystemHandle:
    """One subsystem as the GUI reaches it: its state, and the link behind it."""

    state: SubsystemState = SubsystemState.DOWN
    link: object | None = None


@dataclass
class Stef:
    """The accessor the GUI reads gating from."""

    state: StefState = StefState.IDLE
    transport: SubsystemHandle = field(default_factory=SubsystemHandle)
    capture: SubsystemHandle = field(default_factory=SubsystemHandle)
    detect: SubsystemHandle = field(default_factory=SubsystemHandle)


STEF = Stef()
