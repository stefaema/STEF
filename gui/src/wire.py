"""What the registry holds, as JSON.

Every record carries callables the browser has no use for, and which ones to
drop is a decision per field, so each is flattened by hand.
"""

from __future__ import annotations

from typing import Any

from shared import bench_api
from shared.bench_api import (
    Action,
    BenchTest,
    ParamSpec,
    Readiness,
    Result,
    Subsystem,
)
from shared.bench_api.params import choices, initial, needs_fetch, options_name
from shared.bench_api.results import StepOutcome


def readiness(verdict: Readiness | None) -> dict[str, Any]:
    """Return a verdict as the two things a disabled control needs.

    A probe that falls off the end returns None, which is falsy, so an absent
    answer disables rather than enables.
    """
    if verdict is None:
        return {"ok": False, "reason": None}
    return {"ok": bool(verdict), "reason": verdict.reason}


def param(item: ParamSpec) -> dict[str, Any]:
    """Return one control as everything the browser needs to draw it.

    Options that must be called for cross as the name to call for them by, since
    ports appear when a board is plugged in and a snapshot would say otherwise.
    """
    return {
        "name": item["name"],
        "kind": item["kind"],
        "hint": item.get("hint"),
        "unit": item.get("unit"),
        "min": item.get("min"),
        "max": item.get("max"),
        "options_name": options_name(item),
        "options": None if needs_fetch(item) else list(choices(item)),
        "columns": [param(column) for column in item.get("columns", ())],
    }


def form(params: tuple[ParamSpec, ...]) -> dict[str, Any]:
    """Return a whole form: its controls, and what they start at."""
    return {
        "params": [param(item) for item in params],
        "values": {item["name"]: initial(item) for item in params},
    }


def result(item: Result | None) -> dict[str, Any] | None:
    """Return what a call found, in the one shape every panel renders."""
    if item is None:
        return None
    return {
        "level": item.level.value,
        "summary": item.summary,
        "note": item.note,
        "raw": item.raw.hex(" ") if item.raw else None,
        "fields": [list(pair) for pair in item.fields],
        "table": (
            {"head": list(item.table.head), "rows": [list(r) for r in item.table.rows]}
            if item.table
            else None
        ),
    }


def outcome(item: StepOutcome) -> dict[str, Any]:
    """Return how one step settled."""
    return {
        "status": item.status.value,
        "detail": item.detail,
        "value": result(item.value),
    }


def bench_test(item: BenchTest) -> dict[str, Any]:
    """Return one routine, its prose, its steps and the form that starts it."""
    return {
        "id": item.id,
        "qualified": item.qualified,
        "title": item.title,
        "description": item.description,
        "hazardous": item.hazardous,
        "needs_link": item.needs_link,
        "steps": [{"name": s.name, "title": s.title} for s in item.steps],
        **form(item.params),
    }


def action(item: Action) -> dict[str, Any]:
    """Return one call, its prose, and whether it is worth looking at before it goes."""
    return {
        "name": item.name,
        "qualified": item.qualified,
        "effect": item.effect,
        "description": item.description,
        "hazardous": item.hazardous,
        "has_digest": item.digest is not None,
        **form(item.params),
    }


def subsystem(item: Subsystem, state: str) -> dict[str, Any]:
    """Return one subsystem and everything declared against it."""
    summary, _, body = item.description.partition("\n")
    return {
        "id": item.id,
        "summary": summary.strip(),
        "description": body.strip(),
        "state": state,
        "link": form(item.link.params) if item.link else None,
        "bench_tests": [
            bench_test(t) for t in item.bench_tests.values() if t.needs_link
        ],
        "link_tests": [bench_test(t) for t in item.link_tests],
        "actions": [action(a) for a in item.actions.values()],
    }


def options_for(name: str) -> list[dict[str, Any]]:
    """Return a set of options by the name they are fetched under.

    Callables do not cross, so the browser holds the name and asks for the list
    each time it draws the control.
    """
    for item in bench_api.REGISTRY.subsystems.values():
        for params in _every_form(item):
            for entry in params:
                if options_name(entry) == name:
                    return list(choices(entry))
    raise KeyError(name)


def _every_form(item: Subsystem) -> list[tuple[ParamSpec, ...]]:
    """Return every form one subsystem declares, wherever it declared it."""
    forms = [item.link.params] if item.link else []
    forms += [t.params for t in item.bench_tests.values()]
    forms += [a.params for a in item.actions.values()]
    return forms
