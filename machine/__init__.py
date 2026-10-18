"""The three subsystems of the STEF project as a single concept."""

from machine.activity import AREAS, Activity, Area
from machine.machine import (
    DEMO,
    DEMO_FLAG,
    ROSTER,
    Busy,
    Machine,
    assembled,
    default_roster,
)

__all__ = [
    "AREAS",
    "DEMO",
    "DEMO_FLAG",
    "ROSTER",
    "Activity",
    "Area",
    "Busy",
    "Machine",
    "assembled",
    "default_roster",
]
