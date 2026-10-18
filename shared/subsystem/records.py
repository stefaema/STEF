import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple


class DeclarationError(Exception):
    """A declaration whose failure mode would otherwise be silence."""


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
    """What a step found, in the shape the screen renders."""

    level: Level
    summary: str
    note: str | None = None
    raw: bytes | None = None
    image: bytes | None = None
    fields: tuple[tuple[str, str], ...] = ()
    table: Table | None = None


@dataclass(frozen=True, slots=True)
class Readiness:
    """A verdict on whether a control may be used, carrying the reason when it may not."""

    reason: str | None = None

    def __bool__(self) -> bool:
        """Return whether this may proceed."""
        return self.reason is None

    def __str__(self) -> str:
        """Return the reason, empty when there is none."""
        return self.reason or ""


READY = Readiness()


def blocked(reason: str) -> Readiness:
    """Return a refusal carrying the sentence an operator reads."""
    return Readiness(reason)


def answered(verdict: Readiness | None) -> Readiness:
    """Return what a guard said, reading its silence as consent.

    A blocking verdict is falsy, so this cannot be an `or`: that would read
    every refusal as an approval.
    """
    return READY if verdict is None else verdict


class Option(NamedTuple):
    """One choice whose sent value and read label are not the same string."""

    value: Any
    label: str


Options = Sequence[Any] | Callable[..., Sequence[Any]]


@dataclass(frozen=True, slots=True)
class Input:
    """One value a routine needs, and everything a control needs to ask for it."""

    name: str
    kind: str
    hint: str | None = None
    unit: str | None = None
    min: int | None = None
    max: int | None = None
    options: Options | None = None
    columns: tuple["Input", ...] = ()
