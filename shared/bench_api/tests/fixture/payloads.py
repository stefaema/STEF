"""The annotated payloads a form is derived from, which declare nothing."""

from dataclasses import dataclass, field
from enum import IntEnum, IntFlag


class Element(IntEnum):
    """Which heating element."""

    UPPER = 0
    LOWER = 1


class Watched(IntFlag):
    """What is being watched while it heats."""

    TEMPERATURE = 1
    CURRENT = 2


@dataclass
class Row:
    """One step of a ramp."""

    celsius: int
    minutes: int


@dataclass
class RampArgs:
    """What a ramp takes."""

    element: Element
    celsius: int = field(metadata={"doc": "where it settles"})
    hold: bool = False
    watching: Watched = Watched.TEMPERATURE
    seal: bytes = b""
    steps: list[Row] = field(default_factory=list)
