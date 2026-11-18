"""The operator's routes. Each one reads a form, calls GuiModel, and renders what it holds.

The model starts with the server and closes with it: on shutdown every running test
is let end, and every subsystem is stopped and disconnected.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from gui.src import render, view
from gui.src.bindings import ScreenBindings
from gui.src.forms import values_from
from gui.src.i18n import gettext, ngettext
from gui.src.model import GuiModel, Refused
from shared import logs
from shared.diagnostics import CommandView, InputView, TestView

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
# Seconds between comments on an idle event stream, so nothing between closes it.
KEEPALIVE_S = 15.0

templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_gettext_callables(gettext, ngettext, newstyle=True)  # pyright: ignore[reportAttributeAccessIssue]
templates.env.filters.update(render.FILTERS)
templates.env.globals.update(render.GLOBALS)

model = GuiModel()
bindings = ScreenBindings(model, templates)
log = logs.as_component("gui")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    log.info("writing to {}", logs.start())
    model.start()
    bindings.start()
    yield
    bindings.close()
    await run_in_threadpool(model.close)


app = FastAPI(title="STEF", lifespan=lifespan)


# ── Finding what a route names ───────────────────────────────────────────────


def served_subsystem(subsystem_id: str) -> str:
    if not model.has_subsystem(subsystem_id):
        raise HTTPException(404, f"no subsystem {subsystem_id!r}")
    return subsystem_id


def declared_test(subsystem_id: str, test_key: str) -> TestView:
    try:
        return model.test_view(served_subsystem(subsystem_id), test_key)
    except KeyError:
        raise HTTPException(404, f"no test {subsystem_id}.{test_key}") from None


def declared_command(subsystem_id: str, command_key: str) -> CommandView:
    subsystem_view = model.subsystem_view(served_subsystem(subsystem_id))
    found = next(
        (one for one in subsystem_view.commands if one.key == command_key), None
    )
    if found is None:
        raise HTTPException(404, f"no command {subsystem_id}.{command_key}")
    return found


def link_target(subsystem_id: str) -> InputView:
    link = model.subsystem_view(served_subsystem(subsystem_id)).link
    if link is None or link.target is None:
        raise HTTPException(404, f"{subsystem_id} has no link")
    return link.target


def options_still_loading(inputs: tuple[InputView, ...], form: Any) -> bool:
    """Whether a live option list has not arrived yet, so the form cannot be judged."""
    return any(
        one.kind == "choice"
        and one.reload is not None
        and not str(form.get(one.name, "")).strip()
        for one in inputs
    )


def fragment(request: Request, template: str, template_context: dict[str, Any]) -> Any:
    return templates.TemplateResponse(request, template, template_context)


def page(request: Request, subsystem_id: str | None, tool: str) -> Any:
    """Return the whole page, or only #main when HTMX asked for it."""
    template_context = view.tool_context(model, subsystem_id, tool)
    partial = request.headers.get("hx-request") == "true"
    template = "diagnostics/main.html" if partial else "diagnostics/index.html"
    return fragment(request, template, template_context)


# ── Pages and the event stream ───────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/diagnostics")


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> Any:
    return page(request, model.first_subsystem_id(), "link")


@app.get("/diagnostics/events")
async def screen_events() -> StreamingResponse:
    """Stream every change the screen shows to one browser, as server-sent events."""
    events = bindings.connect()

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    yield await asyncio.wait_for(events.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bindings.disconnect(events)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/diagnostics/{subsystem_id}", response_class=HTMLResponse)
def subsystem_page(request: Request, subsystem_id: str) -> Any:
    return page(request, served_subsystem(subsystem_id), "link")


@app.get("/diagnostics/{subsystem_id}/{tool}", response_class=HTMLResponse)
def tool_page(request: Request, subsystem_id: str, tool: str) -> Any:
    served_subsystem(subsystem_id)
    if tool not in view.TOOLS or (
        tool != "link" and not model.link_is_up(subsystem_id)
    ):
        return RedirectResponse(f"/diagnostics/{subsystem_id}")
    return page(request, subsystem_id, tool)


# ── The link ─────────────────────────────────────────────────────────────────


@app.post("/diagnostics/{subsystem_id}/link/readiness", response_class=HTMLResponse)
async def link_readiness(request: Request, subsystem_id: str) -> Any:
    target = link_target(subsystem_id)
    form = await request.form()
    if options_still_loading((target,), form):
        return fragment(
            request,
            "diagnostics/link/actions.html",
            view.link_tool_context(model, subsystem_id, probe_answered=False),
        )
    submitted = values_from((target,), form).get(target.name, "")
    readiness = await run_in_threadpool(model.probe_target, subsystem_id, submitted)
    return fragment(
        request,
        "diagnostics/link/actions.html",
        view.link_tool_context(
            model, subsystem_id, probe_refusal=readiness.reason, probe_answered=True
        ),
    )


@app.post("/diagnostics/{subsystem_id}/link/connect", response_class=HTMLResponse)
async def connect(request: Request, subsystem_id: str) -> Any:
    target = link_target(subsystem_id)
    submitted = values_from((target,), await request.form()).get(target.name, "")
    action_error = None
    try:
        await run_in_threadpool(model.connect, subsystem_id, submitted)
    except Refused as refused:
        action_error = str(refused)
    return fragment(
        request,
        "diagnostics/main.html",
        view.link_tool_context(
            model, subsystem_id, action_error=action_error, probe_answered=True
        ),
    )


@app.post("/diagnostics/{subsystem_id}/link/disconnect", response_class=HTMLResponse)
async def disconnect(request: Request, subsystem_id: str) -> Any:
    link_target(subsystem_id)
    action_error = None
    try:
        await run_in_threadpool(model.disconnect, subsystem_id)
    except Refused as refused:
        action_error = str(refused)
    return fragment(
        request,
        "diagnostics/main.html",
        view.link_tool_context(model, subsystem_id, action_error=action_error),
    )


# ── Stopping, and the alarm when a stop could not be sent ────────────────────


@app.post("/diagnostics/{subsystem_id}/stop", response_class=HTMLResponse)
async def stop(request: Request, subsystem_id: str) -> Any:
    served_subsystem(subsystem_id)
    action_error = None
    try:
        await run_in_threadpool(model.request_stop, subsystem_id)
    except Refused as refused:
        action_error = str(refused)
    return fragment(
        request,
        "diagnostics/main.html",
        view.link_tool_context(model, subsystem_id, action_error=action_error),
    )


@app.post("/diagnostics/{subsystem_id}/alarm/acknowledge", response_class=HTMLResponse)
async def acknowledge_alarm(request: Request, subsystem_id: str) -> Any:
    served_subsystem(subsystem_id)
    await run_in_threadpool(model.acknowledge_stop_alarm, subsystem_id)
    return fragment(
        request,
        "diagnostics/stop_alarm.html",
        view.page_context(model, subsystem_id, "link"),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@app.post(
    "/diagnostics/{subsystem_id}/tests/{test_key}/run", response_class=HTMLResponse
)
async def run_test(request: Request, subsystem_id: str, test_key: str) -> Any:
    test = declared_test(subsystem_id, test_key)
    form_values = values_from(test.inputs, await request.form())
    try:
        await run_in_threadpool(model.start_test, subsystem_id, test_key, form_values)
    except Refused as refused:
        raise HTTPException(409, str(refused)) from refused
    return fragment(
        request,
        "diagnostics/tests/steps.html",
        view.test_card_context(model, subsystem_id, test_key),
    )


@app.post(
    "/diagnostics/{subsystem_id}/tests/{test_key}/stop", response_class=HTMLResponse
)
async def stop_test(request: Request, subsystem_id: str, test_key: str) -> Any:
    declared_test(subsystem_id, test_key)
    try:
        await run_in_threadpool(model.request_stop, subsystem_id)
    except Refused as refused:
        raise HTTPException(409, str(refused)) from refused
    return fragment(
        request,
        "diagnostics/tests/steps.html",
        view.test_card_context(model, subsystem_id, test_key),
    )


@app.get(
    "/diagnostics/{subsystem_id}/tests/{test_key}/steps", response_class=HTMLResponse
)
def test_steps(request: Request, subsystem_id: str, test_key: str) -> Any:
    declared_test(subsystem_id, test_key)
    return fragment(
        request,
        "diagnostics/tests/steps.html",
        view.test_card_context(model, subsystem_id, test_key),
    )


@app.post(
    "/diagnostics/{subsystem_id}/tests/{test_key}/answer", response_class=HTMLResponse
)
async def answer_question(request: Request, subsystem_id: str, test_key: str) -> Any:
    test = declared_test(subsystem_id, test_key)
    prompt = test.last.prompt if test.last is not None else None
    if prompt is None:
        raise HTTPException(409, gettext("Nothing is being asked"))
    form_values = values_from((prompt.question,), await request.form())
    try:
        await run_in_threadpool(
            model.answer_question,
            subsystem_id,
            form_values.get(prompt.question.name, ""),
        )
    except Refused as refused:
        raise HTTPException(409, str(refused)) from refused
    return HTMLResponse("")


# ── Commands ─────────────────────────────────────────────────────────────────


@app.get("/diagnostics/{subsystem_id}/commands/panel", response_class=HTMLResponse)
def commands_panel(
    request: Request, subsystem_id: str, group: str | None = None
) -> Any:
    return fragment(
        request,
        "diagnostics/commands/panel.html",
        view.commands_tool_context(model, served_subsystem(subsystem_id), group),
    )


@app.get("/diagnostics/{subsystem_id}/commands/method", response_class=HTMLResponse)
def commands_method(request: Request, subsystem_id: str, key: str | None = None) -> Any:
    group = key.rpartition(".")[0] if key else None
    return fragment(
        request,
        "diagnostics/commands/method.html",
        view.commands_tool_context(model, served_subsystem(subsystem_id), group, key),
    )


@app.post(
    "/diagnostics/{subsystem_id}/commands/{command_key}/run",
    response_class=HTMLResponse,
)
async def call_command(request: Request, subsystem_id: str, command_key: str) -> Any:
    command = declared_command(subsystem_id, command_key)
    form_values = values_from(command.inputs, await request.form())
    command_reply: dict[str, Any]
    try:
        result = await run_in_threadpool(
            model.call_command, subsystem_id, command_key, form_values
        )
        command_reply = {"result": result, "refusal": None}
    except Refused as refused:
        command_reply = {"result": None, "refusal": str(refused)}
    template_context = view.commands_tool_context(
        model, subsystem_id, command.group, command_key
    )
    template_context["command_reply"] = command_reply
    return fragment(request, "diagnostics/commands/reply.html", template_context)


# ── Form helpers: live option lists, and one more row of a group ─────────────


@app.get(
    "/diagnostics/{subsystem_id}/options/{item_key}/{input_name}",
    response_class=HTMLResponse,
)
async def option_list(
    request: Request,
    subsystem_id: str,
    item_key: str,
    input_name: str,
    refresh: int = 0,
) -> Any:
    served_subsystem(subsystem_id)
    try:
        offered = await run_in_threadpool(
            model.options, subsystem_id, item_key, input_name, bool(refresh)
        )
    except KeyError as exc:
        raise HTTPException(
            404, f"no options for {subsystem_id}.{item_key}.{input_name}"
        ) from exc
    return fragment(
        request, "diagnostics/options.html", {"offered": offered, "chosen": None}
    )


@app.get(
    "/diagnostics/{subsystem_id}/row/{item_key}/{input_name}",
    response_class=HTMLResponse,
)
def group_row(
    request: Request,
    subsystem_id: str,
    item_key: str,
    input_name: str,
    index: int = 0,
    uid: str = "",
) -> Any:
    subsystem_view = model.subsystem_view(served_subsystem(subsystem_id))
    declared = next(
        (
            one
            for one in (*subsystem_view.tests, *subsystem_view.commands)
            if one.key == item_key
        ),
        None,
    )
    if declared is None:
        raise HTTPException(404, f"no test or command {subsystem_id}.{item_key}")
    spec = next(
        (
            one
            for one in view.fields_of(
                declared.inputs, model.cached_options, subsystem_id, item_key
            )
            if one.name == input_name
        ),
        None,
    )
    if spec is None:
        raise HTTPException(
            404, f"{subsystem_id}.{item_key} declares no group {input_name!r}"
        )
    return fragment(
        request,
        "diagnostics/row.html",
        {"spec": spec, "name": input_name, "index": index, "uid": uid or input_name},
    )


app.mount("/web", StaticFiles(directory=str(WEB)), name="web")

__all__ = ["app", "bindings", "model"]
