from __future__ import annotations

import asyncio
import json
import time
import traceback
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gui.src import render, view
from gui.src.forms import values_from
from gui.src.i18n import gettext, ngettext
from gui.src.render import OPTIONS
from gui.src.runner import Record, Stream, call_off_loop, start_run
from machine import AREAS, Activity, Area, Busy, Machine
from shared import logs
from shared.diagnostics import LINK_KEY, Diagnosable, Prompt, StepOutcome, as_json
from shared.diagnostics.views import view_of_test
from shared.subsystem import (
    Input,
    Linked,
    NotReady,
    Result,
    answered,
    blank_values,
    coerced,
    options_are_live,
)

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
HEARTBEAT = 15.0
STARTING = 1.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    wake()
    yield


app = FastAPI(title="STEF", lifespan=lifespan)
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_gettext_callables(gettext, ngettext, newstyle=True)  # pyright: ignore[reportAttributeAccessIssue]
templates.env.filters.update(render.FILTERS)
templates.env.globals.update(render.GLOBALS)

stream = Stream()
runs = Stream()
stef = Machine()
log = logs.as_component("gui")


def wake() -> None:
    written = logs.start()
    logs.to(stream.sink)
    log.info("writing to {}", written)
    stef.assemble()
    stream.say("gui", "ok", "gui", gettext("Backend ready"))


def diagnosed(name: str | None) -> Diagnosable | None:
    found = stef.subsystems.get(name) if name else None
    return found if isinstance(found, Diagnosable) else None


def subsystem_of(name: str) -> Any:
    found = diagnosed(name)
    if found is None:
        raise HTTPException(404, f"no subsystem {name!r}")
    return found


def _test_of(sub: Any, key: str) -> Any:
    try:
        return sub.test(key)
    except KeyError:
        raise HTTPException(404, f"no test {sub.id}.{key}") from None


def _command_of(sub: Any, key: str) -> Any:
    try:
        return sub.command(key)
    except KeyError:
        raise HTTPException(404, f"no command {sub.id}.{key}") from None


def _target_of(sub: Any) -> Input:
    if not isinstance(sub, Linked):
        raise HTTPException(404, f"{sub.id} has no link")
    return type(sub).target


def _refusal(activity: Activity) -> str:
    if activity is Activity.CONFIGURING:
        return gettext("There are unsaved changes")
    if activity is Activity.SCANNING:
        return gettext("A scan is running")
    return gettext("A test is running")


def _area_refusals() -> dict[str, str | None]:
    held = stef.activity
    return {
        area.value: _refusal(held) if held and AREAS[area] is not held else None
        for area in Area
    }


def _failed(name: str, exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    stream.say(name, "error", "result", message)
    stream.say(name, "error", "traceback", "".join(traceback.format_exception(exc)))
    return message


def _link_state(name: str) -> str:
    return stef.link_state_of(name).value


def _shown(values: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in values.items())


# ── Starting one run ─────────────────────────────────────────────────────────

OUTCOME_LEVEL = {"failed": "error", "error": "error", "warned": "warn"}


def _reporting(name: str, key: str) -> Callable[[str, Any], None]:
    def report(event: str, item: Any) -> None:
        if event == "started":
            runs.say(name, "ok", "started", key, {"key": key})
            return
        if event == "done":
            run = subsystem_of(name).last_run(key)
            settled = run.verdict() if run is not None else None
            status = settled.value if settled is not None else "skipped"
            runs.say(name, "ok", "done", key, {"key": key, "status": status})
            return
        if event == "error":
            runs.say(name, "error", "error", str(item), {"key": key})
            return
        if isinstance(item, Prompt):
            asked = item.question.hint or item.question.name
            runs.say(name, "ok", "prompt", asked, {"key": key})
            return
        if isinstance(item, StepOutcome):
            packed = as_json(item)
            runs.say(
                name,
                OUTCOME_LEVEL.get(packed["status"], "ok"),
                "outcome",
                packed["detail"],
                {"key": key, "outcome": packed},
            )

    return report


def _begin(name: str, key: str, submitted: dict[str, Any]) -> None:
    sub = subsystem_of(name)
    _test_of(sub, key)
    verdict = sub.readiness(key, operator=True)
    if not verdict:
        raise HTTPException(409, str(verdict))

    stream.say(name, "ok", "command", f"{key}({_shown(submitted)})")
    report = _reporting(name, key)

    def work() -> None:
        sub.run_test(
            key, submitted, lambda said: report("outcome", said), operator=True
        )

    runs.forget()
    began = time.time()
    try:
        start_run(stef, Activity.BENCHING, f"{name}.{key}", work, report)
    except Busy as exc:
        raise HTTPException(409, _refusal(exc.activity)) from exc
    deadline = time.monotonic() + STARTING
    while time.monotonic() < deadline:
        last = sub.last_run(key)
        if last is not None and last.started >= began:
            break
        time.sleep(0.01)


def _answer(sub: Any, form: Any) -> None:
    run = sub.running()
    asked = run.prompt if run is not None else None
    if asked is None:
        raise HTTPException(409, gettext("Nothing is being asked"))
    taken = values_from((asked.question,), form)
    sub.answer(taken.get(asked.question.name, ""))


def _stopped(sub: Any) -> None:
    sub.cancel()
    sub.stop()


# ── The JSON a machine reads ─────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/diagnostics")


@app.get("/api/state")
def machine_state() -> dict[str, Any]:
    return {
        "state": stef.activity.value if stef.activity else "idle",
        "areas": _area_refusals(),
        "subsystems": {name: _link_state(name) for name in stef.subsystems},
    }


@app.get("/api/subsystems")
def declarations() -> list[dict[str, Any]]:
    found = []
    for name in stef.roster:
        if name not in stef.subsystems:
            found.append({"id": name, "available": False})
            continue
        found.append({**as_json(subsystem_of(name).view()), "available": True})
    return found


@app.get("/api/options/{name}/{key}/{input_name}")
async def options_for(name: str, key: str, input_name: str) -> list[dict[str, Any]]:
    sub = subsystem_of(name)
    try:
        return list(await asyncio.to_thread(sub.options, key, input_name))
    except KeyError as exc:
        raise HTTPException(404, f"no options for {name}.{key}.{input_name}") from exc


def _target_value(sub: Any, values: Any) -> Any:
    target = _target_of(sub)
    taken = values_from((target,), values)
    return coerced(target, taken.get(target.name, ""), sub)


@app.post("/api/link/{name}/readiness")
async def link_readiness(name: str, values: dict[str, Any]) -> dict[str, Any]:
    sub = subsystem_of(name)
    chosen = _target_value(sub, values)
    try:
        verdict = answered(await asyncio.to_thread(sub.probe, chosen))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return as_json(verdict)


@app.post("/api/link/{name}/connect")
async def connect(name: str, values: dict[str, Any]) -> dict[str, Any]:
    sub = subsystem_of(name)
    chosen = _target_value(sub, values)
    try:
        await _opened(name, sub, chosen)
    except Busy as exc:
        raise HTTPException(409, _refusal(exc.activity)) from exc
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    return {"ok": True, "reason": None, "link": _link_state(name)}


@app.post("/api/link/{name}/disconnect")
async def disconnect(name: str) -> dict[str, Any]:
    sub = subsystem_of(name)
    _target_of(sub)
    try:
        await _closed(name, sub)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    return {"ok": True, "link": _link_state(name)}


@app.post("/api/run/{name}/{key}")
async def run(name: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
    await asyncio.to_thread(_begin, name, key, values)
    return {"ok": True, "run": f"{name}.{key}"}


@app.post("/api/call/{name}/{key:path}")
async def call(name: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
    sub = subsystem_of(name)
    _command_of(sub, key)
    verdict = sub.readiness(key)
    if not verdict:
        raise HTTPException(409, str(verdict))
    answer = await _called(name, sub, key, values)
    if not answer["ok"]:
        return answer
    packed = as_json(answer["value"]) if answer["value"] else None
    return {"ok": True, "reason": None, "value": packed}


@app.post("/api/answer/{name}")
async def answer(name: str, values: dict[str, Any]) -> dict[str, Any]:
    sub = subsystem_of(name)
    run = sub.running()
    asked = run.prompt if run is not None else None
    if asked is None:
        raise HTTPException(409, gettext("Nothing is being asked"))
    sub.answer(values.get(asked.question.name, values.get("value", "")))
    return {"ok": True}


@app.post("/api/stop/{name}")
async def stop(name: str) -> dict[str, Any]:
    sub = subsystem_of(name)
    stream.say(name, "warn", "command", "stop()")
    try:
        await asyncio.to_thread(_stopped, sub)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc)}
    return {"ok": True, "reason": None}


async def _opened(name: str, sub: Any, chosen: Any) -> None:
    stream.say(name, "ok", "command", f"connect({chosen!r})")
    await call_off_loop(
        stef, Activity.BENCHING, f"{name}.connect", lambda: sub.connect(chosen)
    )
    OPTIONS.forget(name)
    stream.say(name, "ok", "result", gettext("Connected"))


async def _closed(name: str, sub: Any) -> None:
    stream.say(name, "ok", "command", "disconnect()")
    await asyncio.to_thread(sub.disconnect)
    OPTIONS.forget(name)
    stream.say(name, "ok", "result", gettext("Disconnected"))


async def _called(
    name: str, sub: Any, key: str, values: dict[str, Any]
) -> dict[str, Any]:
    stream.say(name, "ok", "command", f"{key}({_shown(values)})")
    try:
        reply: Result = await call_off_loop(
            stef,
            Activity.BENCHING,
            f"{name}.{key}",
            lambda: sub.run_command(key, values),
        )
    except Busy as exc:
        return {"ok": False, "reason": _refusal(exc.activity), "value": None}
    except NotReady as exc:
        return {"ok": False, "reason": str(exc), "value": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "value": None}
    stream.say(name, "ok", "result", reply.summary)
    return {"ok": True, "reason": None, "value": reply}


# ── The HTML an operator reads ───────────────────────────────────────────────


def _log_sources() -> list[dict[str, str]]:
    return [{"id": "all", "label": gettext("All")}] + [
        {"id": name, "label": name} for name in stef.subsystems
    ]


def _fields_for(sub: Any) -> Callable[[Any], Any]:
    return lambda item: view.fields_of(item.inputs, OPTIONS.warm, sub.id, item.key)


def _board(name: str | None, tool: str) -> dict[str, Any]:
    sub = diagnosed(name)
    return {
        "sub": sub,
        "seen": sub.view() if sub is not None else None,
        "tabs": view.subsystem_tabs(stef, name),
        "tool": tool,
        "up": view.is_up(sub) if sub else False,
        "log_sources": _log_sources(),
        "fields_for": _fields_for(sub) if sub else (lambda item: ()),
        "oob": False,
    }


def _link_context(name: str, tool: str, **extra: Any) -> dict[str, Any]:
    held = _board(name, tool)
    sub, seen = held["sub"], held["seen"]
    link = seen.link if seen is not None else None
    held.update(
        connect_fields=view.fields_of((link.target,), OPTIONS.warm, sub.id, LINK_KEY)
        if link is not None and link.target is not None
        else (),
        connect_values=blank_values((type(sub).target,)) if link is not None else {},
        prelink=view.tests_while_down(seen) if seen is not None else [],
        reason=None,
        error=None,
        known=held["up"] or link is None,
    )
    held.update(extra)
    return held


def _commands_context(name: str, group: str | None, key: str | None) -> dict[str, Any]:
    held = _board(name, "commands")
    sub, seen = held["sub"], held["seen"]
    groups = view.command_groups(seen) if seen is not None else []
    held["groups"] = groups
    if not groups:
        return held
    names = [one for one, _ in groups]
    chosen = group if group in names else names[0]
    siblings = dict(groups)[chosen]
    picked = next((one for one in siblings if one.key == key), None)
    command = picked or siblings[0]
    held.update(
        siblings=siblings,
        command=command,
        fields=view.fields_of(command.inputs, OPTIONS.warm, sub.id, command.key),
        blank=blank_values(sub.command(command.key).inputs),
    )
    return held


def _context(name: str | None, tool: str) -> dict[str, Any]:
    if tool == "tests":
        held = _board(name, tool)
        seen = held["seen"]
        held["groups"] = view.test_groups(seen) if seen is not None else []
        return held
    if tool == "commands":
        return _commands_context(name or "", None, None)
    return _link_context(name or "", "link") if name else _board(name, tool)


def _page(request: Request, name: str | None, tool: str) -> Any:
    held = _context(name, tool)
    partial = request.headers.get("hx-request") == "true"
    return templates.TemplateResponse(
        request, "diagnostics/main.html" if partial else "diagnostics/index.html", held
    )


def _fragment(request: Request, template: str, held: dict[str, Any]) -> Any:
    return templates.TemplateResponse(request, template, held)


def _test_context(name: str, key: str, oob: bool = False) -> dict[str, Any]:
    sub = subsystem_of(name)
    seen = view_of_test(sub, sub.test(key), True)
    return {
        "sub": sub,
        "test": seen,
        "uid": render.slug(f"{sub.id}.{seen.key}"),
        "fields_for": _fields_for(sub),
        "oob": oob,
    }


@app.get("/diagnostics/stream/log")
async def log_stream() -> StreamingResponse:
    return _served(stream, "record", _log_html)


@app.get("/diagnostics/stream/runs")
async def run_stream() -> StreamingResponse:
    return _served(runs, "run", _run_html)


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> Any:
    return _page(request, view.first_available(stef), "link")


@app.get("/diagnostics/{name}/commands/panel", response_class=HTMLResponse)
def commands_panel(request: Request, name: str, group: str | None = None) -> Any:
    subsystem_of(name)
    return _fragment(
        request,
        "diagnostics/commands/panel.html",
        _commands_context(name, group, None),
    )


@app.get("/diagnostics/{name}/commands/method", response_class=HTMLResponse)
def commands_method(request: Request, name: str, key: str | None = None) -> Any:
    subsystem_of(name)
    group = key.rpartition(".")[0] if key else None
    return _fragment(
        request,
        "diagnostics/commands/method.html",
        _commands_context(name, group, key),
    )


@app.post("/diagnostics/{name}/commands/{key}/run", response_class=HTMLResponse)
async def commands_run(request: Request, name: str, key: str) -> Any:
    sub = subsystem_of(name)
    declared = _command_of(sub, key)
    verdict = sub.readiness(key)
    held = _commands_context(name, declared.group, key)
    if not verdict:
        held["answer"] = {"ok": False, "reason": str(verdict), "value": None}
        return _fragment(request, "diagnostics/commands/reply.html", held)
    taken = values_from(declared.inputs, await request.form())
    held["answer"] = await _called(name, sub, key, taken)
    return _fragment(request, "diagnostics/commands/reply.html", held)


@app.get("/diagnostics/{name}/options/{key}/{input_name}", response_class=HTMLResponse)
async def options_html(
    request: Request, name: str, key: str, input_name: str, refresh: int = 0
) -> Any:
    sub = subsystem_of(name)
    try:
        offered = await asyncio.to_thread(
            OPTIONS.fetch, sub, key, input_name, bool(refresh)
        )
    except KeyError as exc:
        raise HTTPException(404, f"no options for {name}.{key}.{input_name}") from exc
    return _fragment(
        request, "diagnostics/options.html", {"offered": offered, "chosen": None}
    )


@app.get("/diagnostics/{name}/row/{key}/{input_name}", response_class=HTMLResponse)
def group_row(
    request: Request,
    name: str,
    key: str,
    input_name: str,
    index: int = 0,
    uid: str = "",
) -> Any:
    sub = subsystem_of(name)
    seen = sub.view()
    declared = next(
        (one for one in (*seen.tests, *seen.commands) if one.key == key), None
    )
    if declared is None:
        raise HTTPException(404, f"no test or command {name}.{key}")
    spec = next(
        (
            one
            for one in view.fields_of(declared.inputs, OPTIONS.warm, sub.id, key)
            if one.name == input_name
        ),
        None,
    )
    if spec is None:
        raise HTTPException(404, f"{name}.{key} declares no group {input_name!r}")
    return _fragment(
        request,
        "diagnostics/row.html",
        {"spec": spec, "name": input_name, "index": index, "uid": uid or input_name},
    )


def _options_pending(inputs: Any, form: Any) -> bool:
    return any(
        one.kind == "choice"
        and options_are_live(one)
        and not str(form.get(one.name, "")).strip()
        for one in inputs
    )


@app.post("/diagnostics/{name}/link/readiness", response_class=HTMLResponse)
async def link_readiness_html(request: Request, name: str) -> Any:
    sub = subsystem_of(name)
    target = _target_of(sub)
    form = await request.form()
    if _options_pending((target,), form):
        return _fragment(
            request,
            "diagnostics/link/actions.html",
            _link_context(name, "link", known=False),
        )
    chosen = _target_value(sub, form)
    try:
        verdict = answered(await asyncio.to_thread(sub.probe, chosen))
        reason = None if verdict else verdict.reason
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"
    return _fragment(
        request,
        "diagnostics/link/actions.html",
        _link_context(name, "link", reason=reason, known=True),
    )


@app.post("/diagnostics/{name}/link/connect", response_class=HTMLResponse)
async def connect_html(request: Request, name: str) -> Any:
    sub = subsystem_of(name)
    chosen = _target_value(sub, await request.form())
    error = None
    try:
        await _opened(name, sub, chosen)
    except Busy as exc:
        error = _refusal(exc.activity)
    except Exception as exc:  # noqa: BLE001
        error = _failed(name, exc)
    held = _link_context(name, "link", error=error, known=True)
    return _fragment(request, "diagnostics/main.html", held)


@app.post("/diagnostics/{name}/link/disconnect", response_class=HTMLResponse)
async def disconnect_html(request: Request, name: str) -> Any:
    sub = subsystem_of(name)
    _target_of(sub)
    error = None
    try:
        await _closed(name, sub)
    except Exception as exc:  # noqa: BLE001
        error = _failed(name, exc)
    return _fragment(
        request, "diagnostics/main.html", _link_context(name, "link", error=error)
    )


@app.post("/diagnostics/{name}/stop", response_class=HTMLResponse)
async def stop_html(request: Request, name: str) -> Any:
    sub = subsystem_of(name)
    stream.say(name, "warn", "command", "stop()")
    error = None
    try:
        await asyncio.to_thread(_stopped, sub)
        stream.say(name, "ok", "result", gettext("Stopped"))
    except Exception as exc:  # noqa: BLE001
        error = _failed(name, exc)
    return _fragment(
        request, "diagnostics/main.html", _link_context(name, "link", error=error)
    )


@app.post("/diagnostics/{name}/tests/{key}/run", response_class=HTMLResponse)
async def tests_run(request: Request, name: str, key: str) -> Any:
    sub = subsystem_of(name)
    declared = _test_of(sub, key)
    taken = values_from(declared.inputs, await request.form())
    await asyncio.to_thread(_begin, name, key, taken)
    return _fragment(request, "diagnostics/tests/steps.html", _test_context(name, key))


@app.post("/diagnostics/{name}/tests/{key}/answer", response_class=HTMLResponse)
async def tests_answer(request: Request, name: str, key: str) -> Any:
    sub = subsystem_of(name)
    _test_of(sub, key)
    _answer(sub, await request.form())
    return HTMLResponse("")


@app.get("/diagnostics/{name}", response_class=HTMLResponse)
def diagnostics_for(request: Request, name: str) -> Any:
    subsystem_of(name)
    return _page(request, name, "link")


@app.get("/diagnostics/{name}/{tool}", response_class=HTMLResponse)
def diagnostics_tool(request: Request, name: str, tool: str) -> Any:
    subsystem_of(name)
    return _page(request, name, tool if tool in view.TOOLS else "link")


# ── The stream everything reports on ─────────────────────────────────────────


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_html(event: str, body: str) -> str:
    lines = body.splitlines() or [""]
    return f"event: {event}\n" + "".join(f"data: {one}\n" for one in lines) + "\n"


def _render(template: str, held: dict[str, Any]) -> str:
    return templates.get_template(template).render(**held)


def _log_html(record: Record) -> str:
    return _sse_html("record", _render("log/record.html", {"record": record}))


def _run_html(record: Record) -> str:
    key = (record.data or {}).get("key")
    sub = diagnosed(record.source)
    if not key or sub is None:
        return ": keep-alive\n\n"
    if not any(one.key == key for one in sub.tests):
        return ": keep-alive\n\n"
    held = _test_context(record.source, key, oob=True)
    body = _render("diagnostics/tests/head.html", held) + _render(
        "diagnostics/tests/steps.html", held
    )
    return _sse_html("run", body)


def _served(
    source: Stream, event: str | None, shape: Callable[[Record], str] | None = None
) -> StreamingResponse:
    listener, backlog = source.listen()

    def framed(record: Record) -> str:
        if shape is not None:
            return shape(record)
        return _sse(event or record.kind, record.payload())

    async def body() -> AsyncIterator[str]:
        try:
            for record in backlog:
                yield framed(record)
            while True:
                try:
                    record = await asyncio.to_thread(listener.get, True, HEARTBEAT)
                except Exception:  # noqa: BLE001
                    yield ": keep-alive\n\n"
                    continue
                yield framed(record)
        finally:
            source.drop(listener)

    return StreamingResponse(body(), media_type="text/event-stream")


@app.get("/api/events")
async def events() -> StreamingResponse:
    return _served(stream, "record")


@app.get("/api/runs/events")
async def run_events() -> StreamingResponse:
    return _served(runs, None)


app.mount("/web", StaticFiles(directory=str(WEB)), name="web")

__all__ = ["Activity", "Record", "app", "stef", "stream"]
