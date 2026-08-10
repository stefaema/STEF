"""What a subsystem is doing."""

import enum


class SubsystemState(enum.Enum):
    """Whether one subsystem is reachable. Read off the link, never tracked beside it."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"
