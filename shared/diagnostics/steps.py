import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn

from shared.diagnostics.records import PASSED, Needs, StepStatus
from shared.subsystem import (
    READY,
    DeclarationError,
    Input,
    Readiness,
    Result,
    checked_inputs,
    prose_of,
    titled,
)

if TYPE_CHECKING:
    from shared.diagnostics.runner import Run

MARK = "__diagnostics_step__"

END_EXPECTED_S = 30.0


@dataclass(frozen=True, slots=True)
class StepSpec:
    method: str
    title: str
    description: str = ""
    hazard: str | None = None
    skippable: bool = False
    continue_on_failure: bool = False
    end: bool = False
    expected_s: float | None = None


def step(
    title: str,
    *,
    hazard: str | None = None,
    skippable: bool = False,
    continue_on_failure: bool = False,
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    def mark(method: Callable[..., None]) -> Callable[..., None]:
        setattr(
            method,
            MARK,
            StepSpec(
                method=method.__name__,
                title=title,
                description=inspect.getdoc(method) or "",
                hazard=hazard,
                skippable=skippable,
                continue_on_failure=continue_on_failure,
            ),
        )
        return method

    return mark


def end(
    title: str, *, expected_s: float = END_EXPECTED_S
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    def mark(method: Callable[..., None]) -> Callable[..., None]:
        setattr(
            method,
            MARK,
            StepSpec(
                method=method.__name__,
                title=title,
                description=inspect.getdoc(method) or "",
                end=True,
                expected_s=expected_s,
            ),
        )
        return method

    return mark


class Finish(Exception):
    def __init__(self, detail: str, status: StepStatus, result: Result | None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.result = result


class Skip(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class Test[Sub]:
    __test__ = False

    inputs: ClassVar[tuple[Input, ...]] = ()
    needs: ClassVar[Needs] = Needs.UP

    steps: ClassVar[tuple[StepSpec, ...]] = ()
    end_step: ClassVar[StepSpec | None] = None
    questions: ClassVar[tuple[Input, ...]] = ()

    group: ClassVar[str] = ""
    name: ClassVar[str] = ""
    key: ClassVar[str] = ""
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.group = cls.__module__.rpartition(".")[2]
        cls.name = cls.__name__
        cls.key = f"{cls.group}.{cls.name}"
        summary, body = prose_of(_OwnDoc(cls.__dict__.get("__doc__")))
        cls.title = titled(summary) or cls.__name__
        cls.description = body
        cls.inputs = checked_inputs(cls.inputs)
        cls.steps, cls.end_step = _collected(cls)
        cls.questions = _questions(cls)

    @classmethod
    def can_run(cls, sub: Any) -> Readiness | None:
        return READY

    @classmethod
    def ends_within_s(cls) -> float:
        if cls.end_step is not None and cls.end_step.expected_s is not None:
            return cls.end_step.expected_s
        return END_EXPECTED_S

    @classmethod
    def hazardous(cls) -> bool:
        return any(one.hazard for one in cls.steps)

    def __init__(self, sub: Sub, values: dict[str, Any], run: "Run") -> None:
        self.sub = sub
        self.values = values
        self._run = run

    def report(self, detail: str, result: Result | None = None) -> None:
        self._run.said(detail, result, warned=False)

    def warn(self, detail: str, result: Result | None = None) -> None:
        self._run.said(detail, result, warned=True)

    def measure(
        self,
        name: str,
        value: Any,
        *,
        unit: str | None = None,
        low: float | None = None,
        high: float | None = None,
        expected: Any = None,
    ) -> Any:
        self._run.measured(name, value, unit, low, high, expected)
        return value

    def finish(
        self,
        detail: str = "",
        status: StepStatus = PASSED,
        result: Result | None = None,
    ) -> NoReturn:
        raise Finish(detail, status, result)

    def skip(self, detail: str = "") -> NoReturn:
        raise Skip(detail)

    def checkpoint(self) -> None:
        self._run.checkpoint()

    def ask(self, question: Input, timeout: float = 120.0) -> Any:
        return self._run.ask(question, timeout)


class _OwnDoc:
    def __init__(self, doc: str | None) -> None:
        self.__doc__ = doc


def _collected(cls: type) -> tuple[tuple[StepSpec, ...], StepSpec | None]:
    steps: list[StepSpec] = list(getattr(cls, "steps", ()))
    closing = getattr(cls, "end_step", None)
    own_end: StepSpec | None = None
    for value in cls.__dict__.values():
        found = getattr(value, MARK, None)
        if not isinstance(found, StepSpec):
            continue
        if found.end:
            if own_end is not None:
                raise DeclarationError(
                    f"{cls.__name__} declares a second end step, {found.title!r}"
                )
            own_end = found
            continue
        at = next(
            (i for i, one in enumerate(steps) if one.method == found.method), None
        )
        if at is None:
            steps.append(found)
        else:
            steps[at] = found
    closing = own_end or closing
    titles = [one.title for one in steps] + ([closing.title] if closing else [])
    repeated = sorted({one for one in titles if titles.count(one) > 1})
    if repeated:
        raise DeclarationError(
            f"{cls.__name__} has two steps titled {', '.join(map(repr, repeated))}"
        )
    return tuple(steps), closing


def _questions(cls: type) -> tuple[Input, ...]:
    asked: list[Input] = list(getattr(cls, "questions", ()))
    for name, value in cls.__dict__.items():
        if name != "inputs" and isinstance(value, Input) and value not in asked:
            asked.append(value)
    return checked_inputs(asked)
