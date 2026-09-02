from dataclasses import dataclass

CLEARANCE_HOLE = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5}


@dataclass(frozen=True)
class HeatInsertSpec:
    """A heat-set threaded insert, measured as a truncated cone.

    Attributes:
        thread: the screw it takes, as a metric designation ("M3").
        mouth_diameter: OD at the wide end, the one at the surface.
        end_diameter: OD at the narrow end.
        height: the two ends' separation, along the insert's axis.
    """

    thread: str
    mouth_diameter: float
    end_diameter: float
    height: float

    @property
    def clearance_hole(self) -> float:
        """Bore this thread passes through without engaging."""
        return CLEARANCE_HOLE[self.thread]


INSERT_M3_SHORT = HeatInsertSpec(
    thread="M3", mouth_diameter=4.0, end_diameter=3.8, height=4.0
)
