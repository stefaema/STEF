"""Where a declaration lands, what gates it, and how it is run."""

import dataclasses
import importlib
import pkgutil
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from shared import logs
from shared.bench_api import run_log
from shared.bench_api.inputs import checked_inputs
from shared.bench_api.records import (
    CALL,
    FAILED,
    LINK,
    PRELINK,
    READY,
    SETUP,
    SKIPPED,
    Abandoned,
    Behaviour,
    Category,
    DeclarationError,
    Input,
    Readiness,
    Routine,
    StepOutcome,
    StepStatus,
    SubsystemBench,
    blocked,
)
from shared.subsystem import SubsystemSpec, SubsystemState, prose_of, titled

TESTS = "tests"


# ── What has been declared ───────────────────────────────────────────────────


class Registry:
    """Every subsystem that has been loaded, and every routine under it."""

    def __init__(self) -> None:
        """Start holding nothing, since a declaration arrives by import."""
        self.subsystems: dict[str, SubsystemBench] = {}

    def add_subsystem(self, item: SubsystemBench) -> SubsystemBench:
        """Register one subsystem, refusing a second by the same id."""
        if item.id in self.subsystems:
            raise DeclarationError(f"two subsystems answer to {item.id!r}")
        self.subsystems[item.id] = item
        return item

    def add_routine(self, item: Routine) -> Routine:
        """Register one routine, refusing a second by the same id."""
        owner = self.subsystems[item.subsystem]
        key = f"{item.group}.{item.name}"
        if key in owner.routines:
            raise DeclarationError(f"two routines answer to {item.id!r}")
        owner.routines[key] = item
        return item

    def subsystem(self, subsystem_id: str) -> SubsystemBench:
        """Return the subsystem with this id."""
        return self.subsystems[subsystem_id]

    def routine(self, subsystem_id: str, key: str) -> Routine:
        """Return the routine named `group.name` under one subsystem."""
        return self.subsystems[subsystem_id].routines[key]

    def owner_of(self, module: str) -> SubsystemBench:
        """Return the subsystem whose package the module was written in."""
        owners = [item for item in self.subsystems.values() if item.spec.owns(module)]
        if not owners:
            raise DeclarationError(
                f"{module!r} declares against no subsystem; load its package first"
            )
        return max(owners, key=lambda item: len(item.package))

    def clear(self) -> None:
        """Forget every registration."""
        self.subsystems.clear()


REGISTRY = Registry()


# ── Loading one subsystem ────────────────────────────────────────────────────


def derive(spec: SubsystemSpec) -> SubsystemBench:
    """Import a package and everything below it, so its declarations register.

    Any routine declared beneath the package belongs to the subsystem it names.
    """
    module = importlib.import_module(spec.package)
    found = REGISTRY.add_subsystem(SubsystemBench(spec=spec))
    for info in pkgutil.walk_packages(module.__path__, f"{spec.package}."):
        if not _is_declaration(info.name.removeprefix(f"{spec.package}.")):
            continue
        importlib.import_module(info.name)
    return found


def _is_declaration(under: str) -> bool:
    """Whether a module below a subsystem could declare, rather than test what does."""
    parts = under.split(".")
    return TESTS not in parts and not parts[-1].startswith("test_")


# ── Declaring a routine ──────────────────────────────────────────────────────


def register_routine(
    *,
    module: str,
    group: str,
    name: str,
    title: str,
    description: str = "",
    category: Category = SETUP,
    hazardous: bool = False,
    steps: Sequence[str] = (),
    inputs: Sequence[Input] = (),
    run: Callable[..., Iterator[StepOutcome]],
    can_run: Callable[..., Readiness | None] | None = None,
    can_run_with: Callable[..., Readiness | None] | None = None,
) -> Routine:
    """Register one routine from parts, which is what a generated family has.

    The decorator reads these off a function; a loop over an ABI passes them in.
    """
    owner = REGISTRY.owner_of(module)
    return REGISTRY.add_routine(
        Routine(
            id=f"{owner.id}.{group}.{name}",
            subsystem=owner.id,
            group=group,
            name=name,
            category=category,
            title=title,
            description=description,
            hazardous=hazardous,
            steps=tuple(steps),
            inputs=checked_inputs(inputs),
            do=Behaviour(run=run, can_run=can_run, can_run_with=can_run_with),
        )
    )


def routine(
    *,
    category: Category = SETUP,
    hazardous: bool = False,
    steps: Sequence[str] = (),
    inputs: Sequence[Input] = (),
    can_run: Callable[..., Readiness | None] | None = None,
    can_run_with: Callable[..., Readiness | None] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare one routine, taking its id from where it lives and its prose from its docstring."""

    def declare(target: Callable[..., Any]) -> Callable[..., Any]:
        summary, body = prose_of(target)
        register_routine(
            module=target.__module__,
            group=target.__module__.rpartition(".")[2],
            name=target.__name__,
            title=titled(summary) or target.__name__,
            description=body,
            category=category,
            hazardous=hazardous,
            steps=steps,
            inputs=inputs,
            run=target,
            can_run=can_run,
            can_run_with=can_run_with,
        )
        return target

    return declare


# ── Whether it may be run right now ──────────────────────────────────────────

NEEDS_LINK = (SETUP, CALL)


def readiness_of(item: Routine, state: SubsystemState) -> Readiness:
    """Return whether this routine may run, and the sentence for when it may not.

    The category carries the rule, so a screen full of calls costs one state read
    rather than one question per call.
    """
    if item.category in NEEDS_LINK and state is not SubsystemState.UP:
        return blocked("not connected")
    if item.category is PRELINK and state is SubsystemState.UP:
        return blocked("the link holds the port; disconnect first")
    if item.do.can_run is None:
        return READY
    return _answered(item.do.can_run())


def readiness_with(item: Routine, values: dict[str, Any]) -> Readiness:
    """Return whether this routine may run with these values, which may cost a probe."""
    if item.do.can_run_with is None:
        return READY
    return _answered(item.do.can_run_with(**values))


def _answered(verdict: Readiness | None) -> Readiness:
    """Return what a guard said, reading its silence as consent.

    A blocking verdict is falsy, so this cannot be an `or`: that would read
    every refusal as an approval.
    """
    return READY if verdict is None else verdict


# ── Running one ──────────────────────────────────────────────────────────────


def run_routine(item: Routine, values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Yield each step's outcome as the run reaches it, then whatever it never reached.

    A routine cannot break the stream: an uncaught exception becomes one failed
    step, and abandoning settles the step that raised and skips the rest.

    The run writes itself down here, so no routine has to. A thread started
    inside one does not carry the routine, and is matched by timestamp instead.
    """
    pending = list(item.steps)
    reached = 0
    settled: list[StepStatus] = []
    with logs.logger.contextualize(routine=item.id, started=run_log.start_time()):
        run_log.write_start(item, values)
        began = time.monotonic()
        try:
            for outcome in _stream(item, values, pending, reached):
                run_log.write_step(outcome)
                settled.append(outcome.status)
                yield outcome
        finally:
            run_log.write_end(item, settled, time.monotonic() - began)


def _stream(
    item: Routine,
    values: dict[str, Any],
    pending: list[str],
    reached: int,
) -> Iterator[StepOutcome]:
    """Run one routine, turning whatever it does into a stream that cannot break."""
    try:
        for produced in item.do.run(values):
            outcome = _titled_outcome(produced, pending, reached)
            _consume(pending, outcome.step)
            yield outcome
            reached += 1
    except Abandoned as stop:
        settled = _titled_outcome(stop.outcome, pending, reached)
        _consume(pending, settled.step)
        yield settled
    except Exception as exc:  # noqa: BLE001
        settled = StepOutcome(
            FAILED, f"{type(exc).__name__}: {exc}", step=_next(pending)
        )
        _consume(pending, settled.step)
        yield settled

    for title in pending:
        yield StepOutcome(SKIPPED, "", step=title)


def _titled_outcome(
    outcome: StepOutcome, pending: list[str], reached: int
) -> StepOutcome:
    """Return the outcome carrying a title, from itself or from the preview's next row."""
    if outcome.step:
        return outcome
    title = pending[0] if pending else f"#{reached + 1}"
    return dataclasses.replace(outcome, step=title)


def _consume(pending: list[str], title: str) -> None:
    """Drop a title from the preview, since its row has now settled."""
    if title in pending:
        pending.remove(title)


def _next(pending: list[str]) -> str:
    """Return the title of the row a failure lands on, if the preview named one."""
    return pending[0] if pending else ""


# ── Which routines a link is made of ─────────────────────────────────────────


def link_routine(item: SubsystemBench, name: str) -> Routine | None:
    """Return one of a subsystem's link routines by name, or None where it has none."""
    return next(
        (r for r in item.by_category(LINK) if r.name == name),
        None,
    )
