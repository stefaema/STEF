from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from gui.src.i18n import mark
from machine import Machine
from shared.diagnostics import (
    CommandView,
    InputView,
    Needs,
    SkipReason,
    StepOutcome,
    StepStatus,
    SubsystemView,
    TestView,
)
from shared.subsystem import LinkState, Subsystem

TOOLS = ("link", "tests", "commands")

OUTCOME = {
    "idle": ("radio_button_unchecked", "text-gray-400"),
    "running": ("progress_activity", "text-gray-500"),
    "waiting": ("help", "text-yellow-500"),
    "passed": ("check_circle", "text-green-500"),
    "warned": ("warning", "text-yellow-500"),
    "failed": ("error", "text-red-500"),
    "error": ("error", "text-red-600"),
    "skipped": ("block", "text-gray-400"),
    "unreached": ("block", "text-gray-300"),
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
    "waiting": mark("Waiting for you"),
    "passed": mark("Passed"),
    "warned": mark("Warnings"),
    "failed": mark("Failed"),
    "error": mark("Error"),
    "skipped": mark("Skipped"),
    "unreached": mark("Not reached"),
}

LINK_LABEL = {
    "down": mark("Not linked"),
    "linking": mark("Linking"),
    "up": mark("Linked"),
    "error": mark("Failed"),
}

TOOL_LABEL = {
    "link": mark("Link"),
    "tests": mark("Tests"),
    "commands": mark("Commands"),
}

TOOL_ICON = {"link": "link", "tests": "vital_signs", "commands": "data_object"}

LEVEL_TONE = {
    "ok": "text-green-500",
    "warn": "text-yellow-500",
    "error": "text-red-500",
}

DETAIL_TONE = {
    "failed": "text-red-500",
    "error": "text-red-600",
    "warned": "text-yellow-600 dark:text-yellow-400",
}


@dataclass(frozen=True, slots=True)
class Tab:
    id: str
    label: str
    available: bool
    current: bool


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


@dataclass(frozen=True, slots=True)
class Row:
    title: str
    settled: StepOutcome | None
    status: str
    hazard: str | None
    end: bool


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


def is_up(sub: Subsystem) -> bool:
    return sub.link_state() is LinkState.UP


def tests_while_down(seen: SubsystemView) -> list[TestView]:
    return [one for one in seen.tests if one.needs is Needs.DOWN]


def test_groups(seen: SubsystemView) -> list[tuple[str, list[TestView]]]:
    return _grouped([one for one in seen.tests if one.needs is not Needs.DOWN])


def command_groups(seen: SubsystemView) -> list[tuple[str, list[CommandView]]]:
    return _grouped(list(seen.commands))


def _grouped(items: list[Any]) -> list[tuple[str, list[Any]]]:
    held: dict[str, list[Any]] = {}
    for one in items:
        held.setdefault(one.group, []).append(one)
    return list(held.items())


def group_label(name: str) -> str:
    return name.replace("_", " ").title()


def status_of(test: TestView) -> str:
    last = test.last
    if last is None:
        return "idle"
    if last.running:
        return "waiting" if last.prompt is not None else "running"
    return last.verdict.value if last.verdict else "idle"


def worst_status(tests: list[TestView]) -> str:
    from shared.diagnostics import verdict

    settled = [
        one.last.verdict
        for one in tests
        if one.last is not None and one.last.verdict is not None
    ]
    return verdict(settled).value if settled else "idle"


def end_errored(test: TestView) -> bool:
    last = test.last
    return bool(
        last
        and any(one.end and one.status is StepStatus.ERROR for one in last.outcomes)
    )


def rows_of(test: TestView) -> list[Row]:
    previews = [(one.title, one.hazard, False) for one in test.steps]
    if test.end is not None:
        previews.append((test.end.title, None, True))
    outcomes = list(test.last.outcomes) if test.last else []
    running = bool(test.last and test.last.running)
    rows = []
    for index, (title, hazard, is_end) in enumerate(previews):
        settled = outcomes[index] if index < len(outcomes) else None
        if settled is not None:
            status = settled.status.value
            if (
                settled.status is StepStatus.SKIPPED
                and settled.skipped is SkipReason.NOT_REACHED
            ):
                status = "unreached"
        elif running and index == len(outcomes):
            status = "running"
        else:
            status = "idle"
        rows.append(Row(title, settled, status, hazard, is_end))
    return rows


def fields_of(
    inputs: tuple[InputView, ...], warm: Any, sub_id: str, key: str
) -> tuple[Field, ...]:
    return tuple(_field(one, warm, sub_id, key) for one in inputs)


def _field(spec: InputView, warm: Any, sub_id: str, key: str) -> Field:
    live = spec.reload is not None
    cached = warm(sub_id, key, spec.name) if live else None
    return Field(
        name=spec.name,
        kind=spec.kind,
        hint=spec.hint,
        unit=spec.unit,
        min=spec.min,
        max=spec.max,
        options=cached if live else (list(spec.options) if spec.options else None),
        reload=f"/diagnostics/{sub_id}/options/{key}/{spec.name}" if live else None,
        autoload=live and cached is None,
        row_at=f"/diagnostics/{sub_id}/row/{key}/{spec.name}"
        if spec.kind == "group"
        else None,
        columns=tuple(_field(one, warm, sub_id, key) for one in spec.columns),
    )


__all__ = [
    "DETAIL_TONE",
    "LEVEL_TONE",
    "LINK_LABEL",
    "LINK_MARK",
    "OUTCOME",
    "STATUS_LABEL",
    "TOOLS",
    "TOOL_ICON",
    "TOOL_LABEL",
    "Field",
    "Row",
    "Tab",
    "clock",
    "command_groups",
    "end_errored",
    "fields_of",
    "first_available",
    "group_label",
    "is_up",
    "rows_of",
    "status_of",
    "subsystem_tabs",
    "test_groups",
    "tests_while_down",
    "worst_status",
]
