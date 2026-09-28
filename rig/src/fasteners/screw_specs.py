from dataclasses import dataclass

from fasteners.thread_specs import M3, M5, ThreadSpec


@dataclass(frozen=True)
class ScrewSpec:
    """A screw specification.

    Attributes:
        thread: the screw's thread.
        head_diameter: OD of the head at its widest.
        head_height: how far below the surface the head ends up once sunk flush.
    """

    thread: ThreadSpec
    head_diameter: float
    head_height: float


# ISO 10642. The head is a cone rather than a cylinder, so it sinks flush in
# less depth than a socket head of the same thread would need.
SCREW_M3_COUNTERSUNK = ScrewSpec(thread=M3, head_diameter=6.0, head_height=1.7)
SCREW_M5_COUNTERSUNK = ScrewSpec(thread=M5, head_diameter=10.0, head_height=2.8)
