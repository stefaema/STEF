"""Any record as JSON, by one convention rather than one function per record."""

import dataclasses
import enum
from typing import Any

from shared.bench_api.inputs import (
    blank_values,
    labelled_options,
    options_are_live,
    options_name,
)
from shared.bench_api.records import (
    Input,
    Readiness,
    Routine,
    Subsystem,
    as_field,
)
from shared.bench_api.registry import REGISTRY, readiness_of

# ── The one convention ───────────────────────────────────────────────────────


def as_json(value: Any) -> Any:
    """Return any record as JSON, honouring what each field said about crossing.

    A field marked dropped never crosses, and a callable marked by name crosses
    as the name to fetch it under, since a list captured now would be a snapshot.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        crossed = {
            f.name: _field_as_json(value, f)
            for f in dataclasses.fields(value)
            if f.metadata.get("wire") != "drop"
        }
        for name in _properties_as_fields(type(value)):
            crossed[name] = as_json(getattr(value, name))
        return crossed
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex(" ")
    if isinstance(value, (list, tuple)):
        return [as_json(item) for item in value]
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    return value


def _properties_as_fields(record: type) -> tuple[str, ...]:
    """Return the names of the properties this record asked to be walked as fields."""
    return tuple(
        name for name, attr in vars(record).items() if isinstance(attr, as_field)
    )


def _field_as_json(owner: Any, spec: dataclasses.Field) -> Any:
    """Return one field's value as JSON, or the name a callable is fetched under."""
    value = getattr(owner, spec.name)
    if spec.metadata.get("wire") == "name":
        return None if value is None else getattr(value, "__name__", None)
    return as_json(value)


# ── What a screen receives ───────────────────────────────────────────────────


def input_json(item: Input) -> dict[str, Any]:
    """Return one control, its options inline unless they must be asked for."""
    return {
        **as_json(item),
        "options": None if options_are_live(item) else list(labelled_options(item)),
        "options_name": options_name(item),
        "columns": [input_json(column) for column in item.columns],
    }


def readiness_json(verdict: Readiness | None) -> dict[str, Any]:
    """Return a verdict as the two things a disabled control needs.

    A probe that falls off the end returns None, which is falsy, so an absent
    answer disables rather than enables.
    """
    if verdict is None:
        return {"ok": False, "reason": None}
    return {"ok": bool(verdict), "reason": verdict.reason}


def routine_json(item: Routine, state: Any) -> dict[str, Any]:
    """Return one routine, its form, and whether it may be run right now."""
    return {
        **as_json(item),
        "inputs": [input_json(entry) for entry in item.inputs],
        "blank": blank_values(item.inputs),
        "ready": readiness_json(readiness_of(item, state)),
        "asks_first": item.may_run is not None,
    }


def subsystem_json(item: Subsystem) -> dict[str, Any]:
    """Return one subsystem, its state read once, and every routine under it."""
    state = item.now()
    return {
        "id": item.id,
        "summary": item.summary,
        "description": item.description,
        "state": state.value,
        "routines": [routine_json(r, state) for r in item.routines.values()],
    }


# ── A list nobody could send ahead of time ───────────────────────────────────


def options_named(name: str) -> list[dict[str, Any]]:
    """Return one live option list, by the name its callable crosses under."""
    for item in REGISTRY.subsystems.values():
        for entry in _every_input(item):
            if options_name(entry) == name:
                return list(labelled_options(entry))
    raise KeyError(name)


def _every_input(item: Subsystem) -> list[Input]:
    """Return every input declared under one subsystem, a group's columns included."""
    found: list[Input] = []
    for declared in item.routines.values():
        found += _with_columns(declared.inputs)
    return found


def _with_columns(inputs: tuple[Input, ...]) -> list[Input]:
    """Return these inputs and the columns of any group among them."""
    found: list[Input] = []
    for entry in inputs:
        found.append(entry)
        found += _with_columns(entry.columns)
    return found
