"""Any record as JSON, by one convention rather than one function per record."""

import dataclasses
import enum
import inspect
from typing import Any

from shared.bench_api.inputs import blank_values, labelled_options, options_are_live
from shared.bench_api.records import (
    Behaviour,
    Input,
    Readiness,
    Routine,
    Subsystem,
)
from shared.bench_api.registry import REGISTRY, readiness_of

OPTIONS_ROUTE = "/api/options/{subsystem}/{key}/{name}"

# One payload's worth of answers, keyed by the callable that gave them.
Asked = dict[int, list[dict[str, Any]]]


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


def _is_data(value: Any) -> bool:
    """Whether this is something a record holds, rather than something it uses."""
    return not isinstance(value, Behaviour) and not inspect.ismodule(value)


# ── The options a control is drawn with ──────────────────────────────────────


def _asked_once(item: Input, asked: Asked) -> list[dict[str, Any]]:
    """Return this control's options, asking each live list once per payload.

    Twenty-six controls share one `devices`, and asking it is a round trip to
    the board, so an answer stands for as long as one payload is being built.
    """
    if not options_are_live(item):
        return list(labelled_options(item))
    fetch = id(item.options)
    if fetch not in asked:
        asked[fetch] = list(labelled_options(item))
    return asked[fetch]


def _reload_at(item: Input, owner: Routine | None) -> str | None:
    """Return where this control asks for its options again, or None where it never does.

    A fixed list cannot have moved since the payload was built. A live one can
    have, so it carries the address answering for this control alone.
    """
    if owner is None or not options_are_live(item):
        return None
    return OPTIONS_ROUTE.format(
        subsystem=owner.subsystem,
        key=f"{owner.group}.{owner.name}",
        name=item.name,
    )


def input_json(
    item: Input, owner: Routine | None = None, asked: Asked | None = None
) -> dict[str, Any]:
    """Return one control, drawn with the options it has right now."""
    seen = {} if asked is None else asked
    return {
        "name": item.name,
        "kind": item.kind,
        "hint": item.hint,
        "unit": item.unit,
        "min": item.min,
        "max": item.max,
        "options": _asked_once(item, seen),
        "reload": _reload_at(item, owner),
        "columns": [input_json(column, owner, seen) for column in item.columns],
    }


def options_of(subsystem: str, key: str, name: str) -> list[dict[str, Any]]:
    """Return one control's options as they stand now, found by where the control lives."""
    declared = REGISTRY.routine(subsystem, key)
    found = _input_named(declared.inputs, name)
    if found is None:
        raise KeyError(f"{declared.id} declares no input {name!r}")
    return list(labelled_options(found))


def _input_named(inputs: tuple[Input, ...], name: str) -> Input | None:
    """Return the input of this name, counting a group's columns as inputs too."""
    for entry in inputs:
        if entry.name == name:
            return entry
        deeper = _input_named(entry.columns, name)
        if deeper is not None:
            return deeper
    return None


# ── What a screen receives ───────────────────────────────────────────────────


def readiness_json(verdict: Readiness | None) -> dict[str, Any]:
    """Return a verdict as the two things a disabled control needs.

    A probe that falls off the end returns None, which is falsy, so an absent
    answer disables rather than enables.
    """
    if verdict is None:
        return {"ok": False, "reason": None}
    return {"ok": bool(verdict), "reason": verdict.reason}


def routine_json(
    item: Routine, state: Any, asked: Asked | None = None
) -> dict[str, Any]:
    """Return one routine, its form, and whether it may be run right now."""
    seen = {} if asked is None else asked
    return {
        **as_json(item),
        "inputs": [input_json(entry, item, seen) for entry in item.inputs],
        "blank": blank_values(item.inputs),
        "ready": readiness_json(readiness_of(item, state)),
        "asks_first": item.do.can_run_with is not None,
    }


def subsystem_json(item: Subsystem) -> dict[str, Any]:
    """Return one subsystem, its state read once, and every routine under it."""
    state = item.now()
    asked: Asked = {}
    return {
        "id": item.id,
        "summary": item.summary,
        "description": item.description,
        "state": state.value,
        "routines": [routine_json(r, state, asked) for r in item.routines.values()],
    }
