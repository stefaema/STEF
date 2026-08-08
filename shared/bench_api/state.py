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
