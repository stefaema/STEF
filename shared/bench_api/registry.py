"""What the decorators build, and where it lands."""

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from shared.bench_api.derive import values_to_dataclass
from shared.bench_api.params import ParamSpec
from shared.bench_api.readiness import Readiness
from shared.bench_api.results import StepOutcome, StepStatus


class DeclarationError(Exception):
    """A declaration whose failure mode would otherwise be silence."""


class Abandoned(Exception):
    """Raised by a step to end its run early without failing it.

    A routine that finds there is nothing left to do has not failed, and saying
    so by raising is the only way a step can speak for the steps after it.
    """

    def __init__(
        self,
        detail: str = "",
        status: StepStatus = StepStatus.PASSED,
        value: Any = None,
    ) -> None:
        """Take how this step settled, which is what the run stops on."""
        super().__init__(detail)
        self.outcome = StepOutcome(status, detail, value)


@dataclass(frozen=True, slots=True)
class Step:
    """One numbered thing a bench test does."""

    name: str
    title: str
    run: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class BenchTest:
    """A routine an operator runs by hand to check behaviour."""

    id: str
    subsystem: str
    title: str
    description: str
    steps: tuple[Step, ...]
    params: tuple[ParamSpec, ...]
    hazardous: bool
    needs_link: bool
    target: Any

    @property
    def qualified(self) -> str:
        """Return the id the registry knows this by, which names its subsystem too."""
        return f"{self.subsystem}.{self.id}"

    def run(self, bench: Any = None, **args: Any) -> Iterator[StepOutcome]:
        """Yield each step's outcome in order, as the run reaches it.

        The form is applied where the routine starts, the constructor in the class
        form and the call in the generator one, so no step is handed values it
        does not use. One that raises before any step settles yields a single
        failure.
        """
        yield from _run_steps(self, bench, args)


@dataclass(frozen=True, slots=True)
class Action:
    """One call an operator can make by hand, and what it takes to make it."""

    name: str
    subsystem: str
    effect: str
    description: str
    params: tuple[ParamSpec, ...]
    hazardous: bool
    precondition: Callable[..., Readiness | None] | None
    digest: Callable[..., Any] | None
    target: Callable[..., Any]
    argument_type: type | None

    @property
    def qualified(self) -> str:
        """Return the id the registry knows this by, which names its subsystem too."""
        return f"{self.subsystem}.{self.name}"

    def call(self, values: dict[str, Any]) -> Any:
        """Make the call, with the values as the argument object it takes.

        A target annotated with no dataclass takes none, so the values it was
        handed were never going anywhere and the call is made bare.
        """
        args = values_to_dataclass(self.argument_type, values)
        return self.target() if args is None else self.target(args)


@dataclass(frozen=True, slots=True)
class Link:
    """How a subsystem is reached, and whether it may be reached right now."""

    subsystem: str
    params: tuple[ParamSpec, ...]
    target: type


@dataclass
class Subsystem:
    """One part of the machine, and everything declared against it."""

    id: str
    description: str
    target: type
    package: str
    link: Link | None = None
    bench_tests: dict[str, BenchTest] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)

    @property
    def link_tests(self) -> tuple[BenchTest, ...]:
        """Return the routines that run with no link."""
        return tuple(t for t in self.bench_tests.values() if not t.needs_link)


@dataclass
class Registry:
    """Every subsystem that has been imported, and what each declared."""

    subsystems: dict[str, Subsystem] = field(default_factory=dict)

    def add_subsystem(self, item: Subsystem) -> Subsystem:
        """Register one subsystem, refusing a second by the same id."""
        if item.id in self.subsystems:
            raise DeclarationError(f"two subsystems answer to {item.id!r}")
        self.subsystems[item.id] = item
        return item

    def owner_of(self, module: str) -> Subsystem:
        """Return the subsystem owning the module, which is the innermost enclosing one.

        A declaration finds its subsystem by where it lives, so it never names it
        twice. The boundary is the package holding the decorated class.
        """
        owners = [
            item
            for item in self.subsystems.values()
            if module == item.package or module.startswith(f"{item.package}.")
        ]
        if not owners:
            raise DeclarationError(
                f"{module!r} declares against no subsystem; its package has no @subsystem"
            )
        return max(owners, key=lambda item: len(item.package))

    def add_bench_test(self, item: BenchTest) -> BenchTest:
        """Register one bench test, refusing a second by the same id."""
        owner = self.subsystems[item.subsystem]
        if item.id in owner.bench_tests:
            raise DeclarationError(f"two bench tests answer to {item.qualified!r}")
        owner.bench_tests[item.id] = item
        return item

    def add_action(self, item: Action) -> Action:
        """Register one action, refusing a second by the same name."""
        owner = self.subsystems[item.subsystem]
        if item.name in owner.actions:
            raise DeclarationError(f"two actions answer to {item.qualified!r}")
        owner.actions[item.name] = item
        return item

    def set_link(self, item: Link) -> Link:
        """Register one subsystem's link, refusing a second."""
        owner = self.subsystems[item.subsystem]
        if owner.link is not None:
            raise DeclarationError(f"{item.subsystem!r} already declared a link")
        owner.link = item
        return item

    def subsystem(self, subsystem_id: str) -> Subsystem:
        """Return the subsystem with this id."""
        return self.subsystems[subsystem_id]

    def bench_test(self, qualified: str) -> BenchTest:
        """Return the bench test named `subsystem.id`."""
        subsystem_id, _, rest = qualified.partition(".")
        return self.subsystems[subsystem_id].bench_tests[rest]

    def action(self, qualified: str) -> Action:
        """Return the action named `subsystem.ns.method`."""
        subsystem_id, _, rest = qualified.partition(".")
        return self.subsystems[subsystem_id].actions[rest]

    def clear(self) -> None:
        """Forget every registration."""
        self.subsystems.clear()


REGISTRY = Registry()


def load(package: Any) -> None:
    """Import every module under the package, so its decorators run.

    A decorator runs only when its module is imported, and forgetting one leaves
    a bench test that silently does not appear.
    """
    if isinstance(package, str):
        package = importlib.import_module(package)
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        importlib.import_module(info.name)


# ── Running one ──────────────────────────────────────────────────────────────


def _run_steps(
    test: BenchTest, bench: Any, args: dict[str, Any]
) -> Iterator[StepOutcome]:
    """Yield each step's outcome, or the one failure that stopped it starting."""
    if not inspect.isclass(test.target):
        yield from _run_generator(test, bench, args)
        return

    try:
        instance = test.target(**args)
    except Exception as exc:
        yield StepOutcome(StepStatus.FAILED, f"{type(exc).__name__}: {exc}")
        return

    for reached, step in enumerate(test.steps):
        try:
            yield _as_outcome(step.run(instance, bench))
        except Abandoned as stop:
            yield stop.outcome
            for _ in test.steps[reached + 1 :]:
                yield StepOutcome(StepStatus.SKIPPED, "")
            return
        except Exception as exc:
            yield StepOutcome(StepStatus.FAILED, f"{type(exc).__name__}: {exc}")
            return


def _run_generator(
    test: BenchTest, bench: Any, args: dict[str, Any]
) -> Iterator[StepOutcome]:
    """Yield what the generator form yields, so the two forms look alike."""
    try:
        for produced in test.target(bench, **args):
            yield _as_outcome(produced)
    except Abandoned as stop:
        yield stop.outcome
    except Exception as exc:
        yield StepOutcome(StepStatus.FAILED, f"{type(exc).__name__}: {exc}")


def _as_outcome(produced: Any) -> StepOutcome:
    """Return what a step handed back as a StepOutcome, allowing a bare status."""
    if isinstance(produced, StepOutcome):
        return produced
    if isinstance(produced, StepStatus):
        return StepOutcome(produced, "")
    if produced is None:
        return StepOutcome(StepStatus.PASSED, "")
    raise DeclarationError(f"a step yielded {produced!r}, which is not a StepOutcome")
