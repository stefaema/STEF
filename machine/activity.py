import enum


class Activity(enum.Enum):
    """An activity that the STEF machine can be doing."""

    BENCHING = "benching"
    SCANNING = "scanning"
    CONFIGURING = "configuring"


class Area(enum.Enum):
    """A part of the STEF machine a front end can be in."""

    BENCH = "bench"
    SCAN = "scan"
    CONFIG = "config"


# The areas of the STEF machine and the activities that they correspond to.
AREAS: dict[Area, Activity] = {
    Area.BENCH: Activity.BENCHING,
    Area.SCAN: Activity.SCANNING,
    Area.CONFIG: Activity.CONFIGURING,
}


__all__ = ["AREAS", "Activity", "Area"]
