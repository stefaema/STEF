"""The six declarations a subsystem writes, and the errors they raise at import."""

import inspect
import sys
import typing
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from shared.bench_api.derive import dataclass_to_params, with_declared
from shared.bench_api.params import ParamSpec, validated
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

C = TypeVar("C", bound=type)


def _titles(target: Any) -> tuple[str, str]:
    """Return the docstring's summary line and its body, which is what the screen shows."""
    doc = inspect.getdoc(target) or ""
    summary, _, body = doc.partition("\n")
    return summary.strip(), inspect.cleandoc(body).strip()


def _titled(summary: str) -> str:
    """Return a docstring summary as a title, which is not a sentence.

    A summary line ends in a full stop because it is a sentence and Python says
    so. A title is a label, and every one of them ending in a stop reads as a
    row of unfinished thoughts. Only the last one goes: an abbreviation keeps
    its own.
    """
    return (
        summary[:-1]
        if summary.endswith(".") and not summary.endswith("..")
        else summary
    )


def _identifier(target: Any) -> str:
    """Return the id a class or function is known by, from its own name."""
    name = target.__name__
    out = [name[0].lower()]
    for char in name[1:]:
        out.append(f"_{char.lower()}" if char.isupper() else char)
    return "".join(out).strip("_")


def subsystem(subsystem_id: str, description: str) -> Callable[[C], C]:
    """Declare the class that owns one part of the machine.

    The description is the operator's; the class docstring is the programmer's.
    """

    def declare(target: C) -> C:
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


def link(params: Sequence[ParamSpec] = ()) -> Callable[[C], C]:
    """Declare how a subsystem is reached, and the form that reaches it.

    The parameters are checked against `connect` and `can_connect` at import, so
    renaming one on one side only fails there and not on the first click.
    """
    declared = validated(params)

    def declare(target: C) -> C:
        owner = REGISTRY.owner_of(target.__module__)
        for method in ("can_connect", "connect", "can_disconnect", "disconnect"):
            if not callable(getattr(target, method, None)):
                raise DeclarationError(f"{target.__name__} declares no {method}")

        for method in ("connect", "can_connect"):
            _must_take(getattr(target, method), declared, f"{target.__name__}.{method}")

        REGISTRY.set_link(Link(subsystem=owner.id, params=declared, target=target))
        return target

    return declare


def _must_take(
    receiver: Callable[..., Any], declared: Sequence[ParamSpec], who: str
) -> None:
    """Refuse a form whose receiver does not take every parameter it declares.

    Renaming one end only fails at import rather than on the first click.
    """
    takes = set(inspect.signature(receiver).parameters) - {"self"}
    missing = sorted({p["name"] for p in declared} - takes)
    if missing:
        raise DeclarationError(f"{who} does not take {', '.join(missing)}")


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
            found.append(Step(name=name, title=_titled(summary) or name, run=value))
    return tuple(found)


def _receiver(target: Any) -> Callable[..., Any]:
    """Return the one callable a routine's form is applied to.

    Constructing is what starts the class form and calling is what starts the
    generator one, so each has exactly one place the values arrive.
    """
    return target.__init__ if inspect.isclass(target) else target


def _declare_test(
    target: Any, hazardous: bool, needs_link: bool, params: Sequence[ParamSpec]
) -> Any:
    """Register a bench test in either of its two forms, class or generator."""
    owner = REGISTRY.owner_of(target.__module__)
    summary, body = _titles(target)
    steps = _steps_of(target) if inspect.isclass(target) else ()
    if inspect.isclass(target) and not steps:
        raise DeclarationError(f"{target.__name__} declares no @step")
    declared = validated(params)
    if declared:
        _must_take(_receiver(target), declared, target.__name__)

    REGISTRY.add_bench_test(
        BenchTest(
            id=_identifier(target),
            subsystem=owner.id,
            title=_titled(summary) or _identifier(target),
            description=body,
            steps=steps,
            params=declared,
            hazardous=hazardous,
            needs_link=needs_link,
            target=target,
        )
    )
    return target


def bench_test(
    target: Any = None, *, hazardous: bool = False, params: Sequence[ParamSpec] = ()
) -> Any:
    """Declare a routine an operator runs against a subsystem that is already up."""
    if target is not None:
        return _declare_test(target, hazardous=False, needs_link=True, params=())

    def declare(inner: Any) -> Any:
        return _declare_test(inner, hazardous=hazardous, needs_link=True, params=params)

    return declare


def link_test(
    target: Any = None, *, hazardous: bool = False, params: Sequence[ParamSpec] = ()
) -> Any:
    """Declare a routine that runs before there is a link."""
    if target is not None:
        return _declare_test(target, hazardous=False, needs_link=False, params=())

    def declare(inner: Any) -> Any:
        return _declare_test(
            inner, hazardous=hazardous, needs_link=False, params=params
        )

    return declare


def action(
    name: str,
    *,
    hazardous: bool = False,
    params: Sequence[ParamSpec] = (),
    precondition: Callable[..., Any] | None = None,
    digest: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Declare one call an operator can make, and only what an annotation cannot say.

    The form derives from the arguments; this carries the residue.
    """
    declared = validated(params)

    def declare(function: Callable[..., Any]) -> Callable[..., Any]:
        owner = REGISTRY.owner_of(function.__module__)
        summary, body = _titles(function)
        shape = _argument_type(function)
        derived = dataclass_to_params(shape) if shape is not None else ()
        REGISTRY.add_action(
            Action(
                name=name,
                subsystem=owner.id,
                effect=summary,
                description=body,
                params=with_declared(derived, declared),
                hazardous=hazardous,
                precondition=precondition,
                digest=digest,
                target=function,
                argument_type=shape,
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
