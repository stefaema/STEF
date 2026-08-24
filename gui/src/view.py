from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from gui.src.i18n import mark
from machine import Machine, Subsystem
from shared.bench_api import Category, Routine, readiness_of
from shared.subsystem import SubsystemLinkState

HOUSED = ("link", "prelink", "call")
TOOLS = ("link", "routines", "calls")

OUTCOME = {
    "idle": ("radio_button_unchecked", "text-gray-400"),
    "running": ("progress_activity", "text-gray-500"),
    "passed": ("check_circle", "text-green-500"),
    "warned": ("warning", "text-yellow-500"),
    "failed": ("error", "text-red-500"),
    "skipped": ("block", "text-gray-400"),
}

LINK_MARK = {
    "down": ("link_off", "bg-gray-400", "text-gray-400"),
    "linking": ("sync", "bg-yellow-500", "text-yellow-500"),
    "up": ("link", "bg-green-500", "text-green-500"),
    "error": ("error", "bg-red-500", "text-red-500"),
}

STATUS_LABEL = {
    "idle": mark("Not run"),
    "running": mark("Running"),
    "passed": mark("Passed"),
    "warned": mark("Warnings"),
    "failed": mark("Failed"),
    "skipped": mark("Skipped"),
}

LINK_LABEL = {
    "down": mark("Not linked"),
    "linking": mark("Linking"),
    "up": mark("Linked"),
    "error": mark("Failed"),
}

CATEGORY_LABEL = {
    "setup": mark("Setup"),
    "call": mark("Calls"),
    "link": mark("Link"),
    "prelink": mark("Before connecting"),
}

TOOL_LABEL = {
    "link": mark("Link"),
    "routines": mark("Routines"),
    "calls": mark("Calls"),
}

TOOL_ICON = {"link": "link", "routines": "vital_signs", "calls": "data_object"}

LEVEL_TONE = {
    "ok": "text-green-500",
    "warn": "text-yellow-500",
    "error": "text-red-500",
}

DETAIL_TONE = {
    "failed": "text-red-500",
    "warned": "text-yellow-600 dark:text-yellow-400",
}


@dataclass(frozen=True, slots=True)
class Tab:
    id: str
    label: str
    available: bool
    current: bool


def clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(seconds))


def subsystem_tabs(stef: Machine, current: str | None) -> list[Tab]:
    return [
        Tab(name, name, name in stef.subsystems, name == current)
        for name in stef.roster
    ]


def first_available(stef: Machine) -> str | None:
    return next((name for name in stef.roster if name in stef.subsystems), None)


def is_up(sub: Subsystem[Any]) -> bool:
    return sub.link_state is SubsystemLinkState.UP


def routines_of(sub: Subsystem[Any], category: str) -> list[Routine]:
    return [
        one for one in sub.bench.routines.values() if one.category.value == category
    ]


def connect_routine(sub: Subsystem[Any]) -> Routine | None:
    return next(
        (one for one in routines_of(sub, "link") if one.name == "connect"), None
    )


def disconnect_routine(sub: Subsystem[Any]) -> Routine | None:
    return next(
        (one for one in routines_of(sub, "link") if one.name == "disconnect"), None
    )


def prelink_routines(sub: Subsystem[Any]) -> list[Routine]:
    return sorted(routines_of(sub, "prelink"), key=_prelink_order)


def _prelink_order(item: Routine) -> tuple[int, int]:
    return (0 if item.name == "verify_port" else 1, int(item.hazardous))


def bench_groups(sub: Subsystem[Any]) -> list[tuple[str, list[Routine]]]:
    order: list[str] = []
    held: dict[str, list[Routine]] = {}
    for one in sub.bench.routines.values():
        if one.category.value in HOUSED:
            continue
        held.setdefault(one.category.value, [])
        if one.category.value not in order:
            order.append(one.category.value)
        held[one.category.value].append(one)
    return [(name, held[name]) for name in order]


def call_groups(sub: Subsystem[Any]) -> list[tuple[str, list[Routine]]]:
    order: list[str] = []
    held: dict[str, list[Routine]] = {}
    for one in routines_of(sub, "call"):
        if one.group not in held:
            held[one.group] = []
            order.append(one.group)
        held[one.group].append(one)
    return [(name, held[name]) for name in order]


def routine_at(sub: Subsystem[Any], key: str) -> Routine | None:
    return sub.bench.routines.get(key)


def gate(item: Routine, sub: Subsystem[Any]):
    return readiness_of(item, sub.link_state)


def step_titles(item: Routine, reached: int) -> list[str]:
    if item.steps:
        return list(item.steps)
    return [f"#{index + 1}" for index in range(reached)]


def category_label(name: str) -> str:
    return CATEGORY_LABEL.get(name, name.replace("_", " ").title())


__all__ = [
    "CATEGORY_LABEL",
    "Field",
    "fields_of",
    "DETAIL_TONE",
    "LINK_LABEL",
    "STATUS_LABEL",
    "TOOL_ICON",
    "TOOL_LABEL",
    "HOUSED",
    "LEVEL_TONE",
    "LINK_MARK",
    "OUTCOME",
    "TOOLS",
    "Tab",
    "bench_groups",
    "call_groups",
    "category_label",
    "clock",
    "connect_routine",
    "disconnect_routine",
    "first_available",
    "gate",
    "is_up",
    "prelink_routines",
    "routine_at",
    "routines_of",
    "step_titles",
    "subsystem_tabs",
    "Category",
]


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: str
    hint: str | None
    unit: str | None
    min: int | None
    max: int | None
    options: list[dict[str, Any]] | None
    reload: str | None
    autoload: bool
    row_at: str | None
    columns: tuple["Field", ...]


def fields_of(item: Routine, warm) -> tuple[Field, ...]:
    return tuple(_field(one, item, warm) for one in item.inputs)


def _field(spec, owner: Routine, warm) -> Field:
    from shared.bench_api import labelled_options
    from shared.bench_api.inputs import options_are_live

    live = options_are_live(spec)
    key = f"{owner.group}.{owner.name}"
    reload_at = (
        f"/diagnostics/{owner.subsystem}/options/{key}/{spec.name}" if live else None
    )
    cached = warm(owner.subsystem, key, spec.name) if live else None
    return Field(
        name=spec.name,
        kind=spec.kind,
        hint=spec.hint,
        unit=spec.unit,
        min=spec.min,
        max=spec.max,
        options=cached
        if live
        else (list(labelled_options(spec)) if spec.options is not None else None),
        reload=reload_at,
        autoload=live and cached is None,
        row_at=f"/diagnostics/{owner.subsystem}/row/{key}/{spec.name}"
        if spec.kind == "group"
        else None,
        columns=tuple(_field(one, owner, warm) for one in spec.columns),
    )
