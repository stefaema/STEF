"""What a subsystem is doing, and how a run turned out."""

import enum


class SubsystemState(enum.Enum):
    """Whether one subsystem is reachable. Read off the link, never tracked beside it."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


class Status(enum.Enum):
    """How one step of a bench test turned out."""

    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"
    SKIPPED = "skipped"


class Level(enum.Enum):
    """How much attention a result wants."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"


SEVERITY = (Status.SKIPPED, Status.PASSED, Status.WARNED, Status.FAILED)


def worst(statuses):
    """Return the status a run settles at, which is the worst any step reached."""
    found = list(statuses)
    if not found:
        return Status.SKIPPED
    return max(found, key=SEVERITY.index)
