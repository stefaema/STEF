"""Any record as JSON, by one convention rather than one function per record."""

import dataclasses
import enum
import inspect
from typing import Any

from shared.bench_api.inputs import (
    blank_values,
    labelled_options,
    options_are_live,
    options_name,
)
from shared.bench_api.records import (
    Behaviour,
    Input,
    Readiness,
    Routine,
    Subsystem,
)
from shared.bench_api.registry import REGISTRY, readiness_of

# ── The one convention ───────────────────────────────────────────────────────


def as_json(value: Any) -> Any:
    """Return any record as JSON, leaving out whatever it uses rather than holds.

    What a record uses is a `Behaviour` or a live module, and neither describes
    anything: one is called and the other is asked for state.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: as_json(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if _is_data(getattr(value, f.name))
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex(" ")
    if isinstance(value, (list, tuple)):
        return [as_json(item) for item in value]
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    return value


# ── What a screen receives ───────────────────────────────────────────────────


def _is_data(value: Any) -> bool:
    """Whether this is something a record holds, rather than something it uses."""
    return not isinstance(value, Behaviour) and not inspect.ismodule(value)


def input_json(item: Input) -> dict[str, Any]:
    """Return one control, its options inline unless they must be asked for."""
    return {
        "name": item.name,
        "kind": item.kind,
        "hint": item.hint,
        "unit": item.unit,
        "min": item.min,
        "max": item.max,
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
        "asks_first": item.do.can_run_with is not None,
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
