"""One vocabulary for what a call found, whoever made it."""

from dataclasses import dataclass

from shared.bench_api.state import Level, Status


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
class Outcome:
    """How one step of a bench test settled."""

    status: Status
    detail: str
    value: Result | None = None
