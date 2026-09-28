from dataclasses import dataclass

from fasteners.thread_specs import M3, ThreadSpec


@dataclass(frozen=True)
class HeatInsertSpec:
    """A heat-set threaded insert, measured as a truncated cone.

    Attributes:
        thread: the thread of the screw it takes.
        mouth_diameter: OD at the wide end, the one at the surface.
        end_diameter: OD at the narrow end.
        height: the two ends' separation, along the insert's axis.
    """

    thread: ThreadSpec
    mouth_diameter: float
    end_diameter: float
    height: float


INSERT_M3_SHORT = HeatInsertSpec(
    thread=M3, mouth_diameter=4.0, end_diameter=3.8, height=4.0
)
