import enum
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from shared.subsystem import Input, Result


class StepStatus(enum.Enum):
    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


PASSED = StepStatus.PASSED
WARNED = StepStatus.WARNED
FAILED = StepStatus.FAILED
ERROR = StepStatus.ERROR
CANCELLED = StepStatus.CANCELLED
SKIPPED = StepStatus.SKIPPED

SEVERITY = (ERROR, FAILED, CANCELLED, WARNED, PASSED, SKIPPED)


def verdict(statuses: Sequence[StepStatus]) -> StepStatus:
    return next((one for one in SEVERITY if one in statuses), PASSED)


class SkipReason(enum.Enum):
    NOT_NEEDED = "not_needed"
    NOT_REACHED = "not_reached"
    CANCELLED = "cancelled"


class Needs(enum.Enum):
    UP = "up"
    DOWN = "down"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class Measurement:
    name: str
    value: Any
    unit: str | None = None
    low: float | None = None
    high: float | None = None
    expected: Any = None

    @property
    def within(self) -> bool:
        if self.expected is not None and self.value != self.expected:
            return False
        if self.low is not None and self.value < self.low:
            return False
        if self.high is not None and self.value > self.high:
            return False
        return True

    def limits(self) -> str:
        if self.expected is not None:
            return f"expected {self.expected!r}"
        if self.low is not None and self.high is not None:
            return f"{self.low} to {self.high}"
        if self.low is not None:
            return f"at least {self.low}"
        if self.high is not None:
            return f"at most {self.high}"
        return ""


@dataclass(frozen=True, slots=True)
class StepOutcome:
    step: str
    status: StepStatus
    detail: str = ""
    skipped: SkipReason | None = None
    result: Result | None = None
    measurements: tuple[Measurement, ...] = ()
    answers: tuple[tuple[str, Any], ...] = ()
    end: bool = False


@dataclass(frozen=True, slots=True)
class Prompt:
    test: str
    step: str
    question: Input
    timeout: float


class Cancelled(Exception):
    pass


class Failed(Exception):
    def __init__(self, detail: str, result: Result | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.result = result


class NoAnswer(Exception):
    pass
