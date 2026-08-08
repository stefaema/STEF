"""Turning an annotated dataclass into the form that calls it.

A method's arguments are an object with annotated fields, and an annotation
already says most of what a control needs. So the whole input is
`typing.get_type_hints` and `dataclasses.fields`.
"""

import dataclasses
import enum
import typing

from shared.bench_api.params import (
    Param,
    bitmask,
    boolean,
    choice,
    group,
    integer,
    raw_bytes,
)


class DerivationError(TypeError):
    """A field whose annotation names nothing this contract can draw."""


def params_for(target: type) -> tuple[Param, ...]:
    """Return one Param per annotated field of the dataclass, in declaration order."""
    if not dataclasses.is_dataclass(target):
        raise DerivationError(f"{target!r} is not a dataclass, so it has no fields")

    hints = typing.get_type_hints(target)
    return tuple(
        param_for(target, f.name, hints[f.name])
        for f in dataclasses.fields(target)
        if f.name in hints
    )


def param_for(owner: type, name: str, annotation: object) -> Param:
    """Return the one control an annotation implies, or refuse to guess.

    The last case is an error and not a text box: a type this cannot render is
    something nobody decided how to draw, and failing here names the field.
    """
    origin = typing.get_origin(annotation)
    if origin is list:
        (item,) = typing.get_args(annotation)
        if not (isinstance(item, type) and dataclasses.is_dataclass(item)):
            raise DerivationError(
                f"{owner.__name__}.{name} is a list of {item!r}, which is not a dataclass"
            )
        return group(name, columns=params_for(item))

    if annotation is bool:
        return boolean(name)

    if isinstance(annotation, type) and issubclass(annotation, enum.IntFlag):
        return bitmask(name, annotation)

    if isinstance(annotation, type) and issubclass(annotation, enum.IntEnum):
        return choice(name, annotation)

    if annotation is bytes:
        return raw_bytes(name)

    if annotation is int:
        return integer(name)

    raise DerivationError(
        f"{owner.__name__}.{name} is {annotation!r}, which no parameter kind renders"
    )


def with_declared(
    derived: tuple[Param, ...], declared: tuple[Param, ...]
) -> tuple[Param, ...]:
    """Return the derived form with each declared entry put in the place it names.

    Bounds and units are the residue an annotation cannot carry, so a subsystem
    replaces one field and leaves the rest derived.
    """
    by_name = {param.name: param for param in declared}
    known = {param.name for param in derived}
    unknown = sorted(set(by_name) - known)
    if unknown:
        raise DerivationError(
            f"declared parameters name no such field: {', '.join(unknown)}"
        )
    return tuple(by_name.get(param.name, param) for param in derived)
