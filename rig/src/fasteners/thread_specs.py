from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadSpec:
    """A metric thread, as far as the geometry around it is concerned.

    Attributes:
        designation: the metric name ("M3").
        clearance_bore: bore this thread passes through without engaging.
    """

    designation: str
    clearance_bore: float


# M2 = ThreadSpec(designation="M2", clearance_bore=2.4)
# M2_5 = ThreadSpec(designation="M2.5", clearance_bore=2.9)
M3 = ThreadSpec(designation="M3", clearance_bore=3.4)
# M4 = ThreadSpec(designation="M4", clearance_bore=4.5)
M5 = ThreadSpec(designation="M5", clearance_bore=5.5)
