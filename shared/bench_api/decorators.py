"""The six declarations a subsystem writes, and the errors they raise at import."""

import inspect
import sys
import typing
from collections.abc import Callable, Sequence
from typing import Any

from shared.bench_api.derive import params_for, with_declared
from shared.bench_api.params import Param
from shared.bench_api.registry import (
    REGISTRY,
    Action,
    BenchTest,
    DeclarationError,
    Link,
    Step,
    Subsystem,
)

STEP_MARK = "__bench_step__"


def _titles(target: Any) -> tuple[str, str]:
    """Return the docstring's summary line and its body, which is what the screen shows."""
    doc = inspect.getdoc(target) or ""
    summary, _, body = doc.partition("\n")
    return summary.strip(), inspect.cleandoc(body).strip()


def _identifier(target: Any) -> str:
    """Return the id a class or function is known by, from its own name."""
    name = target.__name__
    out = [name[0].lower()]
    for char in name[1:]:
        out.append(f"_{char.lower()}" if char.isupper() else char)
    return "".join(out).strip("_")


def subsystem(subsystem_id: str, description: str) -> Callable[[type], type]:
    """Declare the class that owns one part of the machine.

    The description is the operator's; the class docstring is the programmer's.
    """

    def declare(target: type) -> type:
        REGISTRY.add_subsystem(
            Subsystem(
                id=subsystem_id,
                description=inspect.cleandoc(description).strip(),
                target=target,
                package=_package_of(target),
            )
        )
        return target

    return declare


def _package_of(target: type) -> str:
    """Return the package a subsystem's class was defined in, which is what it owns."""
    module = sys.modules.get(target.__module__)
    return getattr(module, "__package__", None) or target.__module__


def link(params: Sequence[Param] = ()) -> Callable[[type], type]:
    """Declare how a subsystem is reached, and the form that reaches it.

    The parameters are checked against `connect` and `can_connect` at import, so
    renaming one on one side only fails there and not on the first click.
    """
    declared = tuple(params)

    def declare(target: type) -> type:
        owner = REGISTRY.owner_of(target.__module__)
        for method in ("can_connect", "connect", "can_disconnect", "disconnect"):
            if not callable(getattr(target, method, None)):
                raise DeclarationError(f"{target.__name__} declares no {method}")

        for method in ("connect", "can_connect"):
            takes = set(inspect.signature(getattr(target, method)).parameters) - {
                "self"
            }
            missing = sorted({p.name for p in declared} - takes)
            if missing:
                raise DeclarationError(
                    f"{target.__name__}.{method} does not take {', '.join(missing)}"
                )

        REGISTRY.set_link(Link(subsystem=owner.id, params=declared, target=target))
        return target

    return declare


def step(method: Callable[..., Any]) -> Callable[..., Any]:
    """Mark one method of a bench test as a step.

    A marker only: the class does not exist yet, so `@bench_test` collects.
    """
    setattr(method, STEP_MARK, True)
    return method


def _steps_of(target: type) -> tuple[Step, ...]:
    """Return the marked methods in the order they were defined."""
    found = []
    for name, value in vars(target).items():
        if callable(value) and getattr(value, STEP_MARK, False):
            summary, _ = _titles(value)
            found.append(Step(name=name, title=summary or name, run=value))
    return tuple(found)


def _declare_test(target: Any, hazardous: bool, needs_link: bool) -> Any:
    """Register a bench test in either of its two forms, class or generator."""
    owner = REGISTRY.owner_of(target.__module__)
    summary, body = _titles(target)
    steps = _steps_of(target) if inspect.isclass(target) else ()
    if inspect.isclass(target) and not steps:
        raise DeclarationError(f"{target.__name__} declares no @step")

    REGISTRY.add_bench_test(
        BenchTest(
            id=_identifier(target),
            subsystem=owner.id,
            title=summary or _identifier(target),
            description=body,
            steps=steps,
            hazardous=hazardous,
            needs_link=needs_link,
            target=target,
        )
    )
    return target


def bench_test(target: Any = None, *, hazardous: bool = False) -> Any:
    """Declare a routine an operator runs against a subsystem that is already up."""
    if target is not None:
        return _declare_test(target, hazardous=False, needs_link=True)

    def declare(inner: Any) -> Any:
        return _declare_test(inner, hazardous=hazardous, needs_link=True)

    return declare


def link_test(target: Any) -> Any:
    """Declare a routine that runs before there is a link."""
    return _declare_test(target, hazardous=False, needs_link=False)


def action(
    name: str,
    *,
    hazardous: bool = False,
    params: Sequence[Param] = (),
    precondition: Callable[..., Any] | None = None,
    digest: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Declare one call an operator can make, and only what an annotation cannot say.

    The form derives from the arguments; this carries the residue.
    """
    declared = tuple(params)

    def declare(function: Callable[..., Any]) -> Callable[..., Any]:
        owner = REGISTRY.owner_of(function.__module__)
        summary, body = _titles(function)
        shape = _argument_type(function)
        derived = params_for(shape) if shape is not None else ()
        REGISTRY.add_action(
            Action(
                name=name,
                subsystem=owner.id,
                description="\n\n".join(p for p in (summary, body) if p),
                params=with_declared(derived, declared) if derived else declared,
                hazardous=hazardous,
                precondition=precondition,
                digest=digest,
                target=function,
            )
        )
        return function

    return declare


def _argument_type(function: Callable[..., Any]) -> type | None:
    """Return the dataclass a declaration's form comes from, if its signature names one.

    `def move(args: RawMoveArgs)` derives a form; `def move()` declares none.
    """
    hints = typing.get_type_hints(function)
    hints.pop("return", None)
    return next(iter(hints.values()), None)
