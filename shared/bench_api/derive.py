"""The dataclass a call takes, mapped to controls and rebuilt from what they hold.

An annotation names a Python type, which is less than a control needs: no unit,
no real range, no source for a list of choices. So each field becomes the one
kind its type implies, and a subsystem adds the rest by hand.
"""

import dataclasses
import enum
import typing
from typing import Any

from shared.bench_api.params import (
    ParamSpec,
    bitmask,
    boolean,
    choice,
    group,
    integer,
    raw_bytes,
)


class DerivationError(TypeError):
    """A field whose annotation names nothing this contract can draw."""


def dataclass_to_params(target: type) -> tuple[ParamSpec, ...]:
    """Return one parameter per annotated field of the dataclass, in declaration order."""
    if not dataclasses.is_dataclass(target):
        raise DerivationError(f"{target!r} is not a dataclass, so it has no fields")

    hints = typing.get_type_hints(target)
    return tuple(
        _field_to_param(target, f.name, hints[f.name], f.metadata.get("doc"))
        for f in dataclasses.fields(target)
        if f.name in hints
    )


def _field_to_param(
    owner: type, name: str, annotation: object, note: str | None
) -> ParamSpec:
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
        return group(name, columns=dataclass_to_params(item), hint=note)

    if annotation is bool:
        return boolean(name, hint=note)

    if isinstance(annotation, type) and issubclass(annotation, enum.IntFlag):
        return bitmask(name, annotation, hint=note)

    if isinstance(annotation, type) and issubclass(annotation, enum.IntEnum):
        return choice(name, annotation, hint=note)

    if annotation is bytes:
        return raw_bytes(name, hint=note)

    if annotation is int:
        return integer(name, hint=note)

    raise DerivationError(
        f"{owner.__name__}.{name} is {annotation!r}, which no parameter kind renders"
    )


def with_declared(
    derived: tuple[ParamSpec, ...], declared: tuple[ParamSpec, ...]
) -> tuple[ParamSpec, ...]:
    """Return the derived form with each declared entry put in the place it names.

    Bounds and units are the residue an annotation cannot carry, so a subsystem
    replaces one field and leaves the rest derived.
    """
    by_name = {param["name"]: param for param in declared}
    known = {param["name"] for param in derived}
    unknown = sorted(set(by_name) - known)
    if unknown:
        raise DerivationError(
            f"declared parameters name no such field: {', '.join(unknown)}"
        )
    return tuple(by_name.get(param["name"], param) for param in derived)


# ── And back ─────────────────────────────────────────────────────────────────


def values_to_dataclass(dataclass_type: type | None, values: dict[str, Any]) -> Any:
    """Instantiate the dataclass type with the values it has fields for.

    None when the type is absent or is not a dataclass, which is a call that
    takes no argument object at all.
    """
    if dataclass_type is None or not dataclasses.is_dataclass(dataclass_type):
        return None
    known = {f.name for f in dataclasses.fields(dataclass_type)}
    return dataclass_type(**{k: v for k, v in values.items() if k in known})
