"""The registry as the browser still expects it, until the browser is migrated.

`bench_api` holds one kind of thing now, a routine, and serialises it by one
convention. The screen still asks for the three it used to be told about, so the
translation is a grouping by category and a rename of two keys. Nothing here
decides anything; when `diagnostics.js` speaks routines, this file goes.
"""

from __future__ import annotations

from typing import Any

from shared import bench_api
from shared.bench_api import CALL, LINK, PRELINK, SETUP, Routine, Subsystem

CONNECT = "connect"


def _routine(item: Routine, state: Any) -> dict[str, Any]:
    """Return one routine under the keys a bench test used to cross with."""
    shown = bench_api.routine_json(item, state)
    return {
        "id": f"{item.group}.{item.name}",
        "qualified": item.id,
        "title": item.title,
        "description": item.description,
        "hazardous": item.hazardous,
        "needs_link": item.category in (SETUP, CALL),
        "steps": [{"name": title, "title": title} for title in item.steps],
        "params": shown["inputs"],
        "values": shown["blank"],
    }


def _action(item: Routine, state: Any) -> dict[str, Any]:
    """Return one generated call under the keys an action used to cross with."""
    shown = bench_api.routine_json(item, state)
    return {
        "name": f"{item.group}.{item.name}",
        "qualified": item.id,
        "effect": item.title,
        "description": item.description,
        "hazardous": item.hazardous,
        "has_digest": False,
        "params": shown["inputs"],
        "values": shown["blank"],
    }


def _link(item: Subsystem, state: Any) -> dict[str, Any] | None:
    """Return the connect form, which is the whole of what a link used to declare."""
    connect = bench_api.link_routine(item, CONNECT)
    if connect is None:
        return None
    shown = bench_api.routine_json(connect, state)
    return {"params": shown["inputs"], "values": shown["blank"]}


def subsystem(item: Subsystem, state: str) -> dict[str, Any]:
    """Return one subsystem and everything declared against it."""
    now = item.now()
    return {
        "id": item.id,
        "summary": item.summary,
        "description": item.description,
        "state": state,
        "link": _link(item, now),
        "bench_tests": [_routine(r, now) for r in item.by_category(SETUP)],
        "link_tests": [_routine(r, now) for r in item.by_category(PRELINK)],
        "actions": [_action(r, now) for r in item.by_category(CALL)],
    }


def outcome(item: Any) -> dict[str, Any]:
    """Return how one step settled."""
    return bench_api.as_json(item)


def result(item: Any) -> dict[str, Any] | None:
    """Return what a step found, or nothing where it found nothing worth a panel."""
    return None if item is None else bench_api.as_json(item)


def readiness(verdict: Any) -> dict[str, Any]:
    """Return a verdict as the two things a disabled control needs."""
    return bench_api.readiness_json(verdict)


def link_of(item: Subsystem, name: str) -> Routine:
    """Return one of a subsystem's link routines, or say it declares none."""
    found = bench_api.link_routine(item, name)
    if found is None:
        raise KeyError(f"{item.id} declares no {name}")
    return found


LINK_CATEGORY = LINK
