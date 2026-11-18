import base64
import dataclasses
import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from shared.diagnostics.commands import Command
from shared.diagnostics.records import (
    Needs,
    Prompt,
    StepOutcome,
    StepStatus,
)
from shared.diagnostics.runner import Run
from shared.diagnostics.steps import StepSpec, Test
from shared.subsystem import (
    Input,
    Level,
    LinkState,
    Readiness,
    Result,
    labelled_options,
    options_are_live,
)

if TYPE_CHECKING:
    from shared.diagnostics.diagnosable import Diagnosable

from shared.diagnostics.diagnosable import LINK_KEY


@dataclass(frozen=True, slots=True)
class InputView:
    name: str
    kind: str
    hint: str | None
    unit: str | None
    min: int | None
    max: int | None
    options: tuple[dict[str, Any], ...] | None
    reload: tuple[str, str, str] | None
    columns: tuple["InputView", ...]


@dataclass(frozen=True, slots=True)
class StepView:
    title: str
    description: str
    hazard: str | None
    skippable: bool
    expected_s: float | None


@dataclass(frozen=True, slots=True)
class PromptView:
    step: str
    question: InputView
    timeout: float


@dataclass(frozen=True, slots=True)
class RunView:
    key: str
    started: float
    values: dict[str, Any]
    outcomes: tuple[StepOutcome, ...]
    verdict: StepStatus | None
    running: bool
    cancelled: bool
    prompt: PromptView | None
    stop_requested: float | None
    stopped: Result | None
    stop_unconfirmed: str | None


@dataclass(frozen=True, slots=True)
class TestView:
    key: str
    group: str
    title: str
    description: str
    inputs: tuple[InputView, ...]
    needs: Needs
    readiness: Readiness
    steps: tuple[StepView, ...]
    end: StepView | None
    hazardous: bool
    last: RunView | None


@dataclass(frozen=True, slots=True)
class CommandView:
    key: str
    group: str
    name: str
    title: str
    description: str
    inputs: tuple[InputView, ...]
    needs: Needs
    hazard: str | None
    readiness: Readiness
    last: Result | None


@dataclass(frozen=True, slots=True)
class LinkView:
    state: LinkState
    reason: str | None
    target: InputView | None


@dataclass(frozen=True, slots=True)
class SubsystemView:
    id: str
    summary: str
    description: str
    facts: Result | None
    safe_state: str
    link: LinkView | None
    running: str | None
    tests: tuple[TestView, ...]
    commands: tuple[CommandView, ...]


# ── Building them ────────────────────────────────────────────────────────────


def input_view(item: Input, address: tuple[str, str] | None = None) -> InputView:
    live = options_are_live(item)
    return InputView(
        name=item.name,
        kind=item.kind,
        hint=item.hint,
        unit=item.unit,
        min=item.min,
        max=item.max,
        options=None if live else labelled_options(item),
        reload=(*address, item.name) if live and address else None,
        columns=tuple(input_view(column, address) for column in item.columns),
    )


def step_view(spec: StepSpec) -> StepView:
    return StepView(
        spec.title, spec.description, spec.hazard, spec.skippable, spec.expected_s
    )


def prompt_view(asked: Prompt, address: tuple[str, str]) -> PromptView:
    return PromptView(asked.step, input_view(asked.question, address), asked.timeout)


def run_view(run: Run, sub_id: str) -> RunView:
    address = (sub_id, run.test.key)
    asked = run.prompt
    return RunView(
        key=run.test.key,
        started=run.started,
        values=dict(run.values),
        outcomes=run.settled(),
        verdict=run.verdict(),
        running=not run.done.is_set(),
        cancelled=run.cut_short(),
        prompt=prompt_view(asked, address) if asked else None,
        stop_requested=run.stop_requested,
        stopped=run.stopped,
        stop_unconfirmed=run.stop_unconfirmed,
    )


def view_of_test(sub: "Diagnosable", test: type[Test[Any]], operator: bool) -> TestView:
    address = (sub.id, test.key)
    last = sub.last_run(test.key)
    return TestView(
        key=test.key,
        group=test.group,
        title=test.title,
        description=test.description,
        inputs=tuple(input_view(one, address) for one in test.inputs),
        needs=test.needs,
        readiness=sub.readiness(test.key, operator),
        steps=tuple(step_view(one) for one in test.steps),
        end=step_view(test.end_step) if test.end_step else None,
        hazardous=test.hazardous(),
        last=run_view(last, sub.id) if last else None,
    )


def command_view(sub: "Diagnosable", item: Command) -> CommandView:
    address = (sub.id, item.key)
    return CommandView(
        key=item.key,
        group=item.group,
        name=item.name,
        title=item.title,
        description=item.description,
        inputs=tuple(input_view(one, address) for one in item.inputs),
        needs=item.needs,
        hazard=item.hazard,
        readiness=sub.readiness(item.key),
        last=sub.last_reply(item.key),
    )


def link_view(sub: Any) -> LinkView | None:
    target = getattr(type(sub), "target", None)
    if not isinstance(target, Input):
        return None
    return LinkView(
        state=sub.link_state(),
        reason=sub.link_reason(),
        target=input_view(target, (sub.id, LINK_KEY)),
    )


def subsystem_view(
    sub: "Diagnosable", operator: bool = True, read_facts: bool = True
) -> SubsystemView:
    """Return what a screen shows of sub. read_facts=False leaves facts unread, as None."""
    running = sub.running()
    return SubsystemView(
        id=sub.id,
        summary=sub.summary,
        description=sub.description,
        facts=_facts(sub) if read_facts else None,
        safe_state=sub.safe_state,
        link=link_view(sub),
        running=running.test.key if running else None,
        tests=tuple(view_of_test(sub, one, operator) for one in sub.tests),
        commands=tuple(command_view(sub, one) for one in sub.commands),
    )


def _facts(sub: Any) -> Result | None:
    try:
        return sub.facts()
    except Exception as exc:
        return Result(level=Level.WARN, summary=f"{type(exc).__name__}: {exc}")


# ── As JSON ──────────────────────────────────────────────────────────────────


def as_json(value: Any) -> Any:
    if isinstance(value, Readiness):
        return {"ok": bool(value), "reason": value.reason}
    if isinstance(value, Result):
        return {
            "level": value.level.value,
            "summary": value.summary,
            "note": value.note,
            "raw": None if value.raw is None else value.raw.hex(" "),
            "image": None
            if value.image is None
            else base64.b64encode(value.image).decode(),
            "fields": [[name, said] for name, said in value.fields],
            "table": as_json(value.table),
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            one.name: as_json(getattr(value, one.name))
            for one in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex(" ")
    if isinstance(value, dict):
        return {str(name): as_json(said) for name, said in value.items()}
    if isinstance(value, (tuple, list)):
        return [as_json(one) for one in value]
    return value
