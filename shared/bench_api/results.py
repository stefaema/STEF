"""One vocabulary for what a call found, whoever made it."""

import enum
from dataclasses import dataclass


class StepStatus(enum.Enum):
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


@dataclass(frozen=True, slots=True)
class Table:
    """A heading and its rows, for a result that is a list of things."""

    head: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Result:
    """What a call found, in the shape the screen renders."""

    level: Level
    summary: str
    note: str | None = None
    raw: bytes | None = None
    fields: tuple[tuple[str, str], ...] = ()
    table: Table | None = None


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """How one step of a bench test settled."""

    status: StepStatus
    detail: str
    value: Result | None = None
