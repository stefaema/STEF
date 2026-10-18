"""Every record that crosses between a subsystem and a screen."""

import enum
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from shared.subsystem import SubsystemSpec
from shared.subsystem.records import (
    READY as READY,
)
from shared.subsystem.records import (
    DeclarationError as DeclarationError,
)
from shared.subsystem.records import (
    Input as Input,
)
from shared.subsystem.records import (
    Level as Level,
)
from shared.subsystem.records import (
    Option as Option,
)
from shared.subsystem.records import (
    Options as Options,
)
from shared.subsystem.records import (
    Readiness as Readiness,
)
from shared.subsystem.records import (
    Result as Result,
)
from shared.subsystem.records import (
    Table as Table,
)
from shared.subsystem.records import (
    blocked as blocked,
)

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
class SubsystemBench:
    """Every routine declared under one subsystem's package."""

    spec: SubsystemSpec
    routines: dict[str, Routine] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Return the name this subsystem is known by, its package's last part."""
        return self.spec.id

    @property
    def package(self) -> str:
        """Return the dotted path every declaration under this subsystem starts with."""
        return self.spec.package

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
