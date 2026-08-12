"""What a routine needs, declared once and converted in both directions.

A type says what a value is. A control says how it is picked. An input names
which of the six a value gets, and carries every conversion that choice implies.
"""

import dataclasses
import enum
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from shared.bench_api.records import (
    DeclarationError,
    Input,
    Option,
    Options,
)

KINDS = ("choice", "boolean", "integer", "bitmask", "raw_bytes", "group")


# ── Declaring one ────────────────────────────────────────────────────────────


def choice(name: str, options: Options, *, hint: str | None = None) -> Input:
    """Return a pick-one control over a fixed sequence, an enum, or a live list."""
    return Input(name=name, kind="choice", options=options, hint=hint)


def boolean(name: str, *, hint: str | None = None) -> Input:
    """Return an on-or-off control."""
    return Input(name=name, kind="boolean", hint=hint)


def integer(
    name: str,
    *,
    unit: str | None = None,
    min: int | None = None,
    max: int | None = None,
    hint: str | None = None,
) -> Input:
    """Return a number control, with whatever bounds and unit the subsystem knows."""
    return Input(name=name, kind="integer", unit=unit, min=min, max=max, hint=hint)


def bitmask(name: str, options: Options, *, hint: str | None = None) -> Input:
    """Return a pick-many control over the members of a flag set."""
    return Input(name=name, kind="bitmask", options=options, hint=hint)


def raw_bytes(name: str, *, hint: str | None = None) -> Input:
    """Return a control for bytes a caller assembles themselves."""
    return Input(name=name, kind="raw_bytes", hint=hint)


def group(name: str, *, columns: Sequence[Input], hint: str | None = None) -> Input:
    """Return a repeating row of controls, one column per input given."""
    return Input(name=name, kind="group", columns=tuple(columns), hint=hint)


# ── What a decorator refuses at import ───────────────────────────────────────


def checked_inputs(inputs: Sequence[Input]) -> tuple[Input, ...]:
    """Return the inputs, refusing any that no control could draw."""
    for item in inputs:
        _refuse_undrawable(item)
    return tuple(inputs)


def _refuse_undrawable(item: Input) -> None:
    """Raise on one input whose kind or missing options name nothing that draws."""
    if not item.name:
        raise DeclarationError(f"an input declares no name: {item!r}")
    if item.kind not in KINDS:
        raise DeclarationError(
            f"{item.name!r} is of kind {item.kind!r}, which no control renders"
        )
    if item.kind in ("choice", "bitmask") and item.options is None:
        raise DeclarationError(f"{item.name!r} is a {item.kind} and needs options")
    if item.kind == "group" and not item.columns:
        raise DeclarationError(f"{item.name!r} is a group and needs columns")
    for column in item.columns:
        _refuse_undrawable(column)


# ── The inputs an annotated payload implies ──────────────────────────────────


def inputs_for(payload_type: type | None) -> tuple[Input, ...]:
    """Return one input per annotated field of a dataclass, in declaration order."""
    if payload_type is None:
        return ()
    if not dataclasses.is_dataclass(payload_type):
        raise DeclarationError(
            f"{payload_type!r} is not a dataclass, so it has no fields"
        )

    hints = typing.get_type_hints(payload_type)
    return tuple(
        _field_as_input(payload_type, f.name, hints[f.name], f.metadata.get("doc"))
        for f in dataclasses.fields(payload_type)
        if f.name in hints
    )


def _field_as_input(
    owner: type, name: str, annotation: object, note: str | None
) -> Input:
    """Return the one control an annotation implies, or refuse to guess."""
    if typing.get_origin(annotation) is list:
        (item,) = typing.get_args(annotation)
        if not (isinstance(item, type) and dataclasses.is_dataclass(item)):
            raise DeclarationError(
                f"{owner.__name__}.{name} is a list of {item!r}, which is not a dataclass"
            )
        return group(name, columns=inputs_for(item), hint=note)
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
    raise DeclarationError(
        f"{owner.__name__}.{name} is {annotation!r}, which no control renders"
    )


def overridden(
    derived: Sequence[Input], by_name: Mapping[str, Input]
) -> tuple[Input, ...]:
    """Return the derived inputs with each named one replaced by what was written."""
    unknown = sorted(set(by_name) - {item.name for item in derived})
    if unknown:
        raise DeclarationError(f"overrides name no such field: {', '.join(unknown)}")
    return tuple(by_name.get(item.name, item) for item in derived)


# ── The options a choice or a bitmask offers ─────────────────────────────────


def _fetcher(item: Input) -> Callable[[], Sequence[Any]] | None:
    """Return the callable the options must come from, or None where they are fixed."""
    if callable(item.options) and not isinstance(item.options, type):
        return cast(Callable[[], Sequence[Any]], item.options)
    return None


def options_are_live(item: Input) -> bool:
    """Whether the options are unknown until called for."""
    return _fetcher(item) is not None


def options_name(item: Input) -> str | None:
    """Return the name the options are fetched by, or None where nothing is called."""
    fetch = _fetcher(item)
    return fetch.__name__ if fetch else None


def current_options(item: Input) -> tuple[Any, ...]:
    """Return the options as they stand now, calling for them if that is needed."""
    fetch = _fetcher(item)
    if fetch is not None:
        return tuple(fetch())
    if item.options is None:
        return ()
    return tuple(cast(Iterable[Any], item.options))


def labelled_options(item: Input) -> tuple[dict[str, Any], ...]:
    """Return every option as the value a call takes and the label an operator reads."""
    return tuple(_labelled(value) for value in current_options(item))


def _labelled(value: Any) -> dict[str, Any]:
    """Return one option labelled, an enum by its name and anything else by how it prints."""
    if isinstance(value, Option):
        return {"value": value.value, "label": value.label}
    if isinstance(value, enum.Enum):
        return {"value": value.value, "label": value.name}
    if isinstance(value, (tuple, list)):
        raise DeclarationError(
            f"option {value!r} is a bare sequence; use Option(value, label)"
        )
    return {"value": value, "label": str(value)}


# ── What a blank form holds ──────────────────────────────────────────────────


def blank_values(inputs: Sequence[Input]) -> dict[str, Any]:
    """Return what every control holds before anyone touches it."""
    return {item.name: _blank(item) for item in inputs}


def _blank(item: Input) -> Any:
    """Return what one control holds before anyone touches it."""
    if item.kind == "boolean":
        return False
    if item.kind == "group":
        return []
    if item.kind == "raw_bytes":
        return ""
    if item.kind == "choice":
        picks = labelled_options(item)
        return picks[0]["value"] if picks else None
    return item.min or 0


# ── A filled form, as the Python a routine takes ─────────────────────────────


def coerced_values(
    inputs: Sequence[Input], submitted: Mapping[str, Any]
) -> dict[str, Any]:
    """Return submitted values as the Python each input promises."""
    return {
        item.name: _coerced(item, submitted[item.name])
        for item in inputs
        if item.name in submitted
    }


def _coerced(item: Input, value: Any) -> Any:
    """Return one submitted value as the type its kind promises.

    A form arrives over a transport with a thinner vocabulary than Python's, so
    a number may be text and bytes are certainly text.
    """
    if item.kind == "boolean":
        return bool(value)
    if item.kind in ("integer", "bitmask"):
        return int(value or 0)
    if item.kind == "raw_bytes":
        return as_bytes(value)
    if item.kind == "group":
        return [
            {c.name: _coerced(c, row.get(c.name, 0)) for c in item.columns}
            for row in value or []
        ]
    if item.kind == "choice" and isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


def as_bytes(value: Any) -> bytes:
    """Return hex an operator typed as the bytes it stands for, refusing what is not.

    Spacing and an `0x` are how a datasheet writes it. An odd digit count pads on
    the left, since the digits are a number and padding the right scales it.
    """
    if isinstance(value, bytes):
        return value
    text = "".join(str(value or "").split()).removeprefix("0x")
    if not text:
        return b""
    try:
        return bytes.fromhex(text if len(text) % 2 == 0 else "0" + text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not hexadecimal") from exc
