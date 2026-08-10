"""Turning what the registry holds into what crosses to the browser.

The contract's records are Python objects holding callables: a live option list
is a function, a `Readiness` is an object with `__bool__`, an `Outcome` carries
a `Result`. None of that can be sent, and the test for whether a subsystem's
surface has leaked is exactly that everything crossing is JSON.

So this is the only place that knows both vocabularies. A live option list
crosses as the name it is fetched by, never as the list it happened to return
when the page was built, because ports appear when a board is plugged in.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any

from shared import bench_api
from shared.bench_api import (
    Action,
    BenchTest,
    Kind,
    Param,
    Readiness,
    Result,
    Subsystem,
)
from shared.bench_api.results import Outcome


def readiness(verdict: Readiness | None) -> dict[str, Any]:
    """Return a verdict as the two things a disabled control needs.

    A probe that falls off the end returns None, which is falsy, so an absent
    answer disables rather than enables.
    """
    if verdict is None:
        return {"ok": False, "reason": None}
    return {"ok": bool(verdict), "reason": verdict.reason}


def _option(value: Any) -> dict[str, Any]:
    """Return one option as the value and the label a select needs.

    A live list may hand over either. A bare value labels itself, which is what
    an enum member or a plain string wants; a pair is a subsystem saying that
    what an operator reads and what the call takes are not the same string.
    """
    if isinstance(value, enum.Enum):
        return {"value": value.value, "label": value.name}
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return {"value": value[0], "label": str(value[1])}
    return {"value": value, "label": str(value)}


def _options(param: Param) -> list[dict[str, Any]] | None:
    """Return the options that ship inline, or None where they are fetched live."""
    if param.options is None or param.live:
        return None
    resolved = param.resolved()
    if isinstance(param.options, type) and issubclass(param.options, enum.Enum):
        resolved = list(param.options)
    return [_option(value) for value in resolved]


def param(item: Param) -> dict[str, Any]:
    """Return one control as everything the browser needs to draw it."""
    return {
        "name": item.name,
        "kind": item.kind.value,
        "hint": item.hint,
        "unit": item.unit,
        "min": item.min,
        "max": item.max,
        "catalog": item.catalog,
        "options": _options(item),
        "columns": [param(column) for column in item.columns],
    }


def _default(item: Param) -> Any:
    """Return what a control starts at, so a form is fillable before it is touched."""
    if item.kind is Kind.BOOLEAN:
        return False
    if item.kind is Kind.GROUP:
        return []
    if item.kind is Kind.RAW_BYTES:
        return ""
    if item.kind is Kind.CHOICE:
        options = _options(item)
        return options[0]["value"] if options else None
    return item.min or 0


def form(params: tuple[Param, ...]) -> dict[str, Any]:
    """Return a whole form: its controls, and what they start at."""
    return {
        "params": [param(item) for item in params],
        "values": {item.name: _default(item) for item in params},
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


def outcome(item: Outcome) -> dict[str, Any]:
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


# ── Coming back the other way ────────────────────────────────────────────────


def arguments(params: tuple[Param, ...], values: dict[str, Any]) -> dict[str, Any]:
    """Return submitted values as the Python the declaration expects.

    JSON has one number type and no bytes, so what a form submits is not yet
    what a call takes. Coercing here rather than in each subsystem keeps the
    browser's limitations out of everyone else's code.
    """
    taken = {}
    for item in params:
        if item.name not in values:
            continue
        taken[item.name] = _coerce(item, values[item.name])
    return taken


def _coerce(item: Param, value: Any) -> Any:
    """Return one submitted value as the type its kind promises."""
    if item.kind is Kind.BOOLEAN:
        return bool(value)
    if item.kind in (Kind.INTEGER, Kind.BITMASK):
        return int(value or 0)
    if item.kind is Kind.RAW_BYTES:
        return _hex(value)
    if item.kind is Kind.GROUP:
        return [
            {c.name: _coerce(c, row.get(c.name, 0)) for c in item.columns}
            for row in value or []
        ]
    if (
        item.kind is Kind.CHOICE
        and isinstance(value, str)
        and value.lstrip("-").isdigit()
    ):
        return int(value)
    return value


def _hex(value: Any) -> bytes:
    """Return typed hex as the bytes it stands for, refusing what is not hex."""
    if isinstance(value, bytes):
        return value
    text = "".join(str(value or "").split()).removeprefix("0x")
    if not text:
        return b""
    try:
        return bytes.fromhex(text if len(text) % 2 == 0 else "0" + text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not hexadecimal") from exc


def instance(shape: type | None, taken: dict[str, Any]) -> Any:
    """Return the argument object a declaration's target takes, where it takes one."""
    if shape is None or not dataclasses.is_dataclass(shape):
        return None
    known = {f.name for f in dataclasses.fields(shape)}
    return shape(**{k: v for k, v in taken.items() if k in known})


def catalog(name: str) -> list[dict[str, Any]]:
    """Return a live option list by the name it is fetched under.

    Callables do not cross, so the browser holds the name and asks for the list
    each time it draws the control.
    """
    for item in bench_api.REGISTRY.subsystems.values():
        for params in _every_form(item):
            for entry in params:
                if entry.catalog == name:
                    return [_option(value) for value in entry.resolved()]
    raise KeyError(name)


def _every_form(item: Subsystem) -> list[tuple[Param, ...]]:
    """Return every form one subsystem declares, wherever it declared it."""
    forms = [item.link.params] if item.link else []
    forms += [t.params for t in item.bench_tests.values()]
    forms += [a.params for a in item.actions.values()]
    return forms
