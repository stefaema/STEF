"""Every record as the JSON a screen receives, one function per record."""

from typing import Any

from shared.bench_api.inputs import blank_values, labelled_options, options_are_live
from shared.bench_api.records import (
    Input,
    Readiness,
    Result,
    Routine,
    StepOutcome,
    Table,
)
from shared.bench_api.registry import REGISTRY, readiness_of

OPTIONS_ROUTE = "/api/options/{subsystem}/{key}/{name}"


# ── What a routine takes ─────────────────────────────────────────────────────


def input_json(item: Input, owner: Routine | None = None) -> dict[str, Any]:
    """Return one control, drawn where its options are fixed and addressed where they move."""
    live = options_are_live(item)
    return {
        "name": item.name,
        "kind": item.kind,
        "hint": item.hint,
        "unit": item.unit,
        "min": item.min,
        "max": item.max,
        "options": None if live else list(labelled_options(item)),
        "reload": _reload_at(item, owner) if live else None,
        "columns": [input_json(column, owner) for column in item.columns],
    }


def _reload_at(item: Input, owner: Routine | None) -> str | None:
    """Return where this control asks for its options, or None where there is nobody to ask."""
    if owner is None:
        return None
    return OPTIONS_ROUTE.format(
        subsystem=owner.subsystem,
        key=f"{owner.group}.{owner.name}",
        name=item.name,
    )


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


# ── What a routine reports ───────────────────────────────────────────────────


def outcome_json(item: StepOutcome) -> dict[str, Any]:
    """Return how one step settled."""
    return {
        "status": item.status.value,
        "detail": item.detail,
        "value": None if item.value is None else result_json(item.value),
        "step": item.step,
    }


def result_json(item: Result) -> dict[str, Any]:
    """Return what a step found, in the shape the panel renders."""
    return {
        "level": item.level.value,
        "summary": item.summary,
        "note": item.note,
        "raw": None if item.raw is None else item.raw.hex(" "),
        "fields": [[name, value] for name, value in item.fields],
        "table": None if item.table is None else _table_json(item.table),
    }


def _table_json(item: Table) -> dict[str, Any]:
    """Return a result's heading and rows."""
    return {"head": list(item.head), "rows": [list(row) for row in item.rows]}


# ── What a screen receives ───────────────────────────────────────────────────


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
        "id": item.id,
        "subsystem": item.subsystem,
        "group": item.group,
        "name": item.name,
        "category": item.category.value,
        "title": item.title,
        "description": item.description,
        "hazardous": item.hazardous,
        "steps": list(item.steps),
        "inputs": [input_json(entry, item) for entry in item.inputs],
        "blank": blank_values(item.inputs),
        "ready": readiness_json(readiness_of(item, state)),
        "asks_first": item.do.can_run_with is not None,
    }
