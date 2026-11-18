"""Labels, tones, groupings and form fields for the templates, and the context of every page."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from gui.src.i18n import gettext, mark
from shared.diagnostics import (
    END_EXPECTED_S,
    LINK_KEY,
    CommandView,
    InputView,
    Needs,
    SkipReason,
    StepOutcome,
    StepStatus,
    SubsystemView,
    TestView,
    verdict,
)

if TYPE_CHECKING:
    from gui.src.model import GuiModel

TOOLS = ("link", "tests", "commands")

OUTCOME = {
    "idle": ("radio_button_unchecked", "text-gray-400"),
    "running": ("progress_activity", "text-gray-500"),
    "waiting": ("help", "text-yellow-500"),
    "cancelled": ("block", "text-orange-500"),
    "stopping": ("power_settings_new", "text-orange-500"),
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
    "cancelled": mark("Cancelled"),
    "stopping": mark("Stopping"),
    "passed": mark("Passed"),
    "warned": mark("Warnings"),
    "failed": mark("Failed"),
    "error": mark("Error"),
    "skipped": mark("Skipped"),
    "unreached": mark("Not reached"),
}

SKIPPED_BECAUSE = {
    "not_needed": mark("not needed"),
    "not_reached": mark("not reached, after an earlier step failed"),
    "cancelled": mark("cancelled before it ran"),
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
    "cancelled": "text-orange-500",
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
    link_state: str
    alarmed: bool


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
    step_outcome: StepOutcome | None
    status: str
    hazard: str | None
    end: bool


def subsystem_tabs(model: "GuiModel", current: str | None) -> list[Tab]:
    tabs = []
    for subsystem_id in model.roster:
        served = model.has_subsystem(subsystem_id)
        link = model.subsystem_view(subsystem_id).link if served else None
        tabs.append(
            Tab(
                id=subsystem_id,
                label=subsystem_id,
                available=served,
                current=subsystem_id == current,
                link_state=link.state.value if link is not None else "down",
                alarmed=served and model.stop_alarm(subsystem_id) is not None,
            )
        )
    return tabs


def tests_before_connecting(subsystem_view: SubsystemView) -> list[TestView]:
    return [one for one in subsystem_view.tests if one.needs is Needs.DOWN]


def test_groups(subsystem_view: SubsystemView) -> list[tuple[str, list[TestView]]]:
    return _grouped(
        [one for one in subsystem_view.tests if one.needs is not Needs.DOWN]
    )


def command_groups(
    subsystem_view: SubsystemView,
) -> list[tuple[str, list[CommandView]]]:
    return _grouped(list(subsystem_view.commands))


def _grouped(items: list[Any]) -> list[tuple[str, list[Any]]]:
    by_group: dict[str, list[Any]] = {}
    for one in items:
        by_group.setdefault(one.group, []).append(one)
    return list(by_group.items())


def group_label(name: str) -> str:
    return name.replace("_", " ").title()


def status_of(test: TestView) -> str:
    last = test.last
    if last is None:
        return "idle"
    if last.running:
        if last.stop_requested is not None:
            return "stopping"
        return "waiting" if last.prompt is not None else "running"
    return last.verdict.value if last.verdict else "idle"


def worst_status(tests: list[TestView]) -> str:
    settled = [
        one.last.verdict
        for one in tests
        if one.last is not None and one.last.verdict is not None
    ]
    return verdict(settled).value if settled else "idle"


def stop_patience(test: TestView) -> float:
    if test.end is not None and test.end.expected_s is not None:
        return test.end.expected_s
    return END_EXPECTED_S


def stop_waited(test: TestView) -> float:
    last = test.last
    if last is None or last.stop_requested is None:
        return 0.0
    return time.time() - last.stop_requested


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
        step_outcome = outcomes[index] if index < len(outcomes) else None
        if step_outcome is not None:
            status = step_outcome.status.value
            if (
                step_outcome.status is StepStatus.SKIPPED
                and step_outcome.skipped is SkipReason.NOT_REACHED
            ):
                status = "unreached"
        elif running and index == len(outcomes):
            status = "running"
        else:
            status = "idle"
        rows.append(Row(title, step_outcome, status, hazard, is_end))
    return rows


# ── Form fields ──────────────────────────────────────────────────────────────

CachedOptions = Callable[[str, str, str], list[dict[str, Any]] | None]


def fields_of(
    inputs: tuple[InputView, ...],
    cached_options: CachedOptions,
    subsystem_id: str,
    item_key: str,
) -> tuple[Field, ...]:
    return tuple(_field(one, cached_options, subsystem_id, item_key) for one in inputs)


def _field(
    spec: InputView, cached_options: CachedOptions, subsystem_id: str, item_key: str
) -> Field:
    live = spec.reload is not None
    cached = cached_options(subsystem_id, item_key, spec.name) if live else None
    return Field(
        name=spec.name,
        kind=spec.kind,
        hint=spec.hint,
        unit=spec.unit,
        min=spec.min,
        max=spec.max,
        options=cached if live else (list(spec.options) if spec.options else None),
        reload=f"/diagnostics/{subsystem_id}/options/{item_key}/{spec.name}"
        if live
        else None,
        autoload=live and cached is None,
        row_at=f"/diagnostics/{subsystem_id}/row/{item_key}/{spec.name}"
        if spec.kind == "group"
        else None,
        columns=tuple(
            _field(one, cached_options, subsystem_id, item_key) for one in spec.columns
        ),
    )


def blank_form_values(inputs: tuple[InputView, ...]) -> dict[str, Any]:
    """Return the initial value of every control."""
    return {one.name: _blank(one) for one in inputs}


def _blank(spec: InputView) -> Any:
    if spec.kind == "choice":
        return spec.options[0]["value"] if spec.options else None
    if spec.kind == "boolean":
        return False
    if spec.kind == "integer":
        return spec.min or 0
    if spec.kind == "bitmask":
        return 0
    if spec.kind == "raw_bytes":
        return ""
    return []


# ── Template contexts ────────────────────────────────────────────────────────


def log_sources(model: "GuiModel") -> list[dict[str, str]]:
    return [{"id": "all", "label": gettext("All")}] + [
        {"id": one, "label": one} for one in (*model.roster, "gui", "diagnostics")
    ]


def page_context(
    model: "GuiModel", subsystem_id: str | None, tool: str
) -> dict[str, Any]:
    """Return the context that every page and the board use, for one subsystem and tool."""
    subsystem_view = (
        model.subsystem_view(subsystem_id)
        if subsystem_id is not None and model.has_subsystem(subsystem_id)
        else None
    )
    _, focus_holder = model.focus

    def fields_for(item: TestView | CommandView) -> tuple[Field, ...]:
        if subsystem_view is None:
            return ()
        return fields_of(item.inputs, model.cached_options, subsystem_view.id, item.key)

    def field_of(spec: InputView, item_key: str) -> Field:
        assert subsystem_view is not None
        return fields_of((spec,), model.cached_options, subsystem_view.id, item_key)[0]

    return {
        "subsystem_view": subsystem_view,
        "subsystem_tabs": subsystem_tabs(model, subsystem_id),
        "tool": tool,
        "link_is_up": subsystem_view is not None
        and model.link_is_up(subsystem_view.id),
        "stop_alarm": model.stop_alarm(subsystem_view.id)
        if subsystem_view is not None
        else None,
        "focus_holder": focus_holder,
        "log_sources": log_sources(model),
        "fields_for": fields_for,
        "field_of": field_of,
        "oob": False,
    }


def link_tool_context(
    model: "GuiModel", subsystem_id: str, **extra: Any
) -> dict[str, Any]:
    """Return the context of the Link tool, with the connect form and the tests that need the link down."""
    template_context = page_context(model, subsystem_id, "link")
    subsystem_view: SubsystemView | None = template_context["subsystem_view"]
    link = subsystem_view.link if subsystem_view is not None else None
    target = link.target if link is not None else None
    template_context.update(
        connect_fields=fields_of(
            (target,), model.cached_options, subsystem_id, LINK_KEY
        )
        if target is not None
        else (),
        connect_values=blank_form_values((target,)) if target is not None else {},
        tests_before_connecting=tests_before_connecting(subsystem_view)
        if subsystem_view is not None
        else [],
        probe_refusal=None,
        action_error=None,
        probe_answered=template_context["link_is_up"] or link is None,
    )
    template_context.update(extra)
    return template_context


def tests_tool_context(model: "GuiModel", subsystem_id: str) -> dict[str, Any]:
    template_context = page_context(model, subsystem_id, "tests")
    subsystem_view = template_context["subsystem_view"]
    template_context["test_groups"] = (
        test_groups(subsystem_view) if subsystem_view is not None else []
    )
    return template_context


def commands_tool_context(
    model: "GuiModel",
    subsystem_id: str,
    group: str | None = None,
    command_key: str | None = None,
) -> dict[str, Any]:
    """Return the context of the Commands tool. command_key picks the command, otherwise the group's first command is used."""
    template_context = page_context(model, subsystem_id, "commands")
    subsystem_view = template_context["subsystem_view"]
    groups = command_groups(subsystem_view) if subsystem_view is not None else []
    template_context["command_groups"] = groups
    if not groups:
        return template_context
    group_names = [name for name, _ in groups]
    chosen_group = group if group in group_names else group_names[0]
    sibling_commands = dict(groups)[chosen_group]
    picked = next((one for one in sibling_commands if one.key == command_key), None)
    command = picked or sibling_commands[0]
    template_context.update(
        sibling_commands=sibling_commands,
        command=command,
        command_fields=fields_of(
            command.inputs, model.cached_options, subsystem_id, command.key
        ),
        command_blank_values=blank_form_values(command.inputs),
    )
    return template_context


def tool_context(
    model: "GuiModel", subsystem_id: str | None, tool: str
) -> dict[str, Any]:
    if subsystem_id is None:
        return page_context(model, None, tool)
    if tool == "tests":
        return tests_tool_context(model, subsystem_id)
    if tool == "commands":
        return commands_tool_context(model, subsystem_id)
    return link_tool_context(model, subsystem_id)


def test_card_context(
    model: "GuiModel", subsystem_id: str, test_key: str, oob: bool = False
) -> dict[str, Any]:
    """Return the context of one test card, used by routes and by events."""
    template_context = page_context(model, subsystem_id, "tests")
    test = model.test_view(subsystem_id, test_key)
    template_context.update(
        test=test, test_uid=slug(f"{subsystem_id}.{test.key}"), oob=oob
    )
    return template_context


def slug(text: Any) -> str:
    return str(text).replace(".", "-").replace("/", "-")


__all__ = [
    "DETAIL_TONE",
    "LEVEL_TONE",
    "LINK_LABEL",
    "LINK_MARK",
    "OUTCOME",
    "SKIPPED_BECAUSE",
    "STATUS_LABEL",
    "TOOLS",
    "TOOL_ICON",
    "TOOL_LABEL",
    "Field",
    "Row",
    "Tab",
    "blank_form_values",
    "command_groups",
    "commands_tool_context",
    "end_errored",
    "fields_of",
    "group_label",
    "link_tool_context",
    "page_context",
    "rows_of",
    "slug",
    "status_of",
    "stop_patience",
    "stop_waited",
    "subsystem_tabs",
    "test_card_context",
    "test_groups",
    "tests_before_connecting",
    "tests_tool_context",
    "tool_context",
    "worst_status",
]
