"""Every record that crosses between a subsystem and a screen."""

import enum
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, NamedTuple

# What a subsystem package is asked for its state by.
STATE_ATTRIBUTE = "state"

# ── How a declaration refuses ────────────────────────────────────────────────


class DeclarationError(Exception):
    """A declaration whose failure mode would otherwise be silence."""


# ── What a routine says about itself as it runs ──────────────────────────────


class StepStatus(enum.Enum):
    """How one step of a routine turned out."""

    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"
    SKIPPED = "skipped"


PASSED = StepStatus.PASSED
WARNED = StepStatus.WARNED
FAILED = StepStatus.FAILED
SKIPPED = StepStatus.SKIPPED


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
    fields: tuple[tuple[str, str], ...] = ()
    table: Table | None = None


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """How one step settled, carrying the title of the step it settles."""

    status: StepStatus
    detail: str
    value: Result | None = None
    step: str = ""


class Abandoned(Exception):
    """Raised by a routine to end its run early without failing it."""

    def __init__(
        self, detail: str = "", status: StepStatus = PASSED, value: Result | None = None
    ) -> None:
        """Take how the step that raised this settled."""
        super().__init__(detail)
        self.outcome = StepOutcome(status, detail, value)


# ── Whether something may proceed ────────────────────────────────────────────


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


class SubsystemState(enum.Enum):
    """Whether one subsystem is reachable. Read off the package, never tracked beside it."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


# ── What a routine takes ─────────────────────────────────────────────────────


class Option(NamedTuple):
    """One choice whose sent value and read label are not the same string."""

    value: Any
    label: str


# Either a fixed sequence, an enum class, or a zero-argument callable returning one.
Options = Any


@dataclass(frozen=True, slots=True)
class Input:
    """One value a routine needs, and everything a control needs to ask for it."""

    name: str
    kind: str
    hint: str | None = None
    unit: str | None = None
    min: int | None = None
    max: int | None = None
    options: Options = None
    columns: tuple["Input", ...] = ()


# ── What an operator runs ────────────────────────────────────────────────────


class Category(enum.Enum):
    """Which stage of a subsystem's life a routine belongs to."""

    LINK = "link"
    PRELINK = "prelink"
    SETUP = "setup"
    CALL = "call"


LINK = Category.LINK
PRELINK = Category.PRELINK
SETUP = Category.SETUP
CALL = Category.CALL


@dataclass(frozen=True, slots=True)
class Behaviour:
    """What a routine does, and what it says before it does it.

    Held apart from the description because nothing describes a callable: it is
    called, never read, never shown and never serialised.
    """

    run: Callable[..., Iterator[StepOutcome]]
    can_run: Callable[[], Readiness | None] | None = None
    can_run_with: Callable[..., Readiness | None] | None = None


@dataclass(frozen=True, slots=True)
class Routine:
    """One thing an operator runs, whatever it does and however many steps it takes."""

    id: str
    subsystem: str
    group: str
    name: str
    category: Category
    title: str
    description: str
    hazardous: bool
    steps: tuple[str, ...]
    inputs: tuple[Input, ...]
    do: Behaviour


@dataclass
class Subsystem:
    """One part of the machine, and every routine declared under its package."""

    module: Any = None
    summary: str = ""
    description: str = ""
    routines: dict[str, Routine] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Return the name this subsystem is known by, its package's last part."""
        return self.package.rpartition(".")[2]

    @property
    def package(self) -> str:
        """Return the dotted path every declaration under this subsystem starts with."""
        return self.module.__name__

    def now(self) -> SubsystemState:
        """Return the state the package reports when asked, never one remembered here.

        Asked through the module rather than through a function captured at load,
        so a package that reports differently later is believed.
        """
        reported = getattr(self.module, STATE_ATTRIBUTE, None)
        return reported() if reported is not None else SubsystemState.DOWN

    def by_category(self, category: Category) -> tuple[Routine, ...]:
        """Return every routine of one category, in declaration order."""
        return tuple(r for r in self.routines.values() if r.category is category)


# ── One line on the stream every subsystem writes to ─────────────────────────


@dataclass(frozen=True, slots=True)
class LogEvent:
    """One line on the log: who said it, how loud, and when."""

    time: float
    source: str
    level: Level
    text: str
