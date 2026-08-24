from __future__ import annotations

import asyncio
import json
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
from gui.src.runs import RUNS, address_of
from machine import Activity, Busy, Machine, subsystem_json
from shared import bench_api, logs
from shared.bench_api.inputs import options_are_live

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
HEARTBEAT = 15.0


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


def subsystem_of(name: str) -> Any:
    try:
        return stef.subsystem(name)
    except KeyError:
        raise HTTPException(404, f"no subsystem {name!r}") from None


def _running(what: str) -> str:
    return gettext("{what} is running").format(what=what)


def _failed(name: str, exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    stream.say(name, "error", "result", message)
    stream.say(name, "error", "traceback", "".join(traceback.format_exception(exc)))
    return message


def _link_state(name: str) -> str:
    return stef.link_state_of(name).value


def _settle(declared: Any, values: dict[str, Any]) -> None:
    for outcome in bench_api.run_routine(declared, values):
        if outcome.status is bench_api.FAILED:
            raise RuntimeError(outcome.detail)


def _one_result(declared: Any, values: dict[str, Any]) -> Any:
    settled = list(bench_api.run_routine(declared, values))
    failed = next((o for o in settled if o.status is bench_api.FAILED), None)
    if failed is not None:
        raise RuntimeError(failed.detail)
    return next((o.value for o in settled if o.value is not None), None)


# ── Starting one run ─────────────────────────────────────────────────────────

OUTCOME_LEVEL = {"failed": "error", "warned": "warn"}


def _as_outcome(item: Any) -> bench_api.StepOutcome:
    if isinstance(item, bench_api.StepOutcome):
        return item
    return bench_api.StepOutcome(bench_api.FAILED, str(item.get("error", "")), None, "")


def _reporting(name: str, key: str) -> Callable[[str, Any], None]:
    settled: list[bench_api.StepStatus] = []
    address = address_of(name, key)

    def report(event: str, item: Any) -> None:
        if event == "started":
            runs.say(name, "ok", "started", key, {"key": key})
            return
        if event == "done":
            verdict = bench_api.verdict(settled)
            RUNS.finish(address, verdict)
            runs.say(name, "ok", "done", key, {"key": key, "status": verdict.value})
            return
        outcome = _as_outcome(item)
        packed = bench_api.outcome_json(outcome)
        settled.append(outcome.status)
        RUNS.record(address, outcome)
        runs.say(
            name,
            OUTCOME_LEVEL.get(packed["status"], "ok"),
            "outcome",
            packed["detail"],
            {"key": key, "outcome": packed},
        )

    return report


def _begin(name: str, key: str, values: dict[str, Any]) -> None:
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    test = record.bench.routines[key]
    verdict = bench_api.readiness_of(test, record.link_state)
    if not verdict:
        raise HTTPException(409, str(verdict))

    shown = ", ".join(f"{k}={v!r}" for k, v in values.items())
    stream.say(name, "ok", "command", f"{key}({shown})")

    what = f"{name}.{key}"
    runs.forget()
    RUNS.begin(what, values)
    try:
        start_run(
            stef,
            Activity.BENCHING,
            what,
            _running(what),
            lambda: bench_api.run_routine(test, values),
            _reporting(name, key),
        )
    except Busy as exc:
        RUNS.finish(what, bench_api.SKIPPED)
        raise HTTPException(409, str(exc)) from exc


# ── The JSON a machine reads ─────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/diagnostics")


@app.get("/api/state")
def machine_state() -> dict[str, Any]:
    return {
        "state": stef.activity.value,
        "busy": stef.busy_with,
        "areas": stef.openings(),
        "subsystems": {name: _link_state(name) for name in stef.subsystems},
    }


@app.get("/api/subsystems")
def declarations() -> list[dict[str, Any]]:
    found = []
    for name in stef.roster:
        if name not in stef.subsystems:
            found.append({"id": name, "available": False})
            continue
        found.append({**subsystem_json(stef.subsystem(name)), "available": True})
    return found


@app.get("/api/options/{name}/{key}/{input_name}")
async def options_for(name: str, key: str, input_name: str) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(bench_api.options_of, name, key, input_name)
    except KeyError as exc:
        raise HTTPException(404, f"no options for {name}.{key}.{input_name}") from exc


def _link_of(name: str, which: str) -> Any:
    found = bench_api.link_routine(subsystem_of(name).bench, which)
    if found is None:
        raise HTTPException(404, f"{name} declares no {which}")
    return found


@app.post("/api/link/{name}/readiness")
async def link_readiness(name: str, values: dict[str, Any]) -> dict[str, Any]:
    declared = _link_of(name, "connect")
    taken = bench_api.coerced_values(declared.inputs, values)
    try:
        verdict = await asyncio.to_thread(
            lambda: bench_api.readiness_with(declared, taken)
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return bench_api.readiness_json(verdict)


@app.post("/api/link/{name}/connect")
async def connect(name: str, values: dict[str, Any]) -> dict[str, Any]:
    declared = _link_of(name, "connect")
    taken = bench_api.coerced_values(declared.inputs, values)
    try:
        await _opened(name, declared, taken)
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    return {"ok": True, "reason": None, "link": _link_state(name)}


@app.post("/api/link/{name}/disconnect")
async def disconnect(name: str) -> dict[str, Any]:
    declared = _link_of(name, "disconnect")
    try:
        await _closed(name, declared)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    return {"ok": True, "link": _link_state(name)}


@app.post("/api/run/{name}/{test_id}")
async def run(name: str, test_id: str, values: dict[str, Any]) -> dict[str, Any]:
    record = subsystem_of(name)
    if test_id not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{test_id}")
    taken = bench_api.coerced_values(record.bench.routines[test_id].inputs, values)
    _begin(name, test_id, taken)
    return {"ok": True, "run": f"{name}.{test_id}"}


@app.post("/api/call/{name}/{key:path}")
async def call(name: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    declared = record.bench.routines[key]
    verdict = bench_api.readiness_of(declared, record.link_state)
    if not verdict:
        raise HTTPException(409, str(verdict))
    taken = bench_api.coerced_values(declared.inputs, values)
    answer = await _called(name, key, declared, taken)
    if not answer["ok"]:
        return answer
    packed = bench_api.result_json(answer["value"]) if answer["value"] else None
    return {"ok": True, "reason": None, "value": packed}


async def _opened(name: str, declared: Any, taken: dict[str, Any]) -> None:
    shown = ", ".join(f"{k}={v!r}" for k, v in taken.items())
    stream.say(name, "ok", "command", f"connect({shown})")
    await call_off_loop(
        stef,
        Activity.BENCHING,
        f"{name}.connect",
        _running(f"{name}.connect"),
        lambda: _settle(declared, taken),
    )
    OPTIONS.forget(name)
    stream.say(name, "ok", "result", gettext("Connected"))


async def _closed(name: str, declared: Any) -> None:
    stream.say(name, "ok", "command", "disconnect()")
    await asyncio.to_thread(lambda: _settle(declared, {}))
    OPTIONS.forget(name)
    stream.say(name, "ok", "result", gettext("Disconnected"))


async def _called(
    name: str, key: str, declared: Any, taken: dict[str, Any]
) -> dict[str, Any]:
    shown = ", ".join(f"{k}={v!r}" for k, v in taken.items())
    stream.say(name, "ok", "command", f"{key}({shown})")
    try:
        answer = await call_off_loop(
            stef,
            Activity.BENCHING,
            f"{name}.{key}",
            _running(f"{name}.{key}"),
            lambda: _one_result(declared, taken),
        )
    except Busy as exc:
        return {"ok": False, "reason": str(exc), "value": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "value": None}
    stream.say(name, "ok", "result", answer.summary if answer else key)
    return {"ok": True, "reason": None, "value": answer}


# ── The HTML an operator reads ───────────────────────────────────────────────


def _log_sources() -> list[dict[str, str]]:
    return [{"id": "all", "label": gettext("All")}] + [
        {"id": name, "label": name} for name in stef.subsystems
    ]


def _board(name: str | None, tool: str) -> dict[str, Any]:
    sub = stef.subsystems.get(name) if name else None
    return {
        "sub": sub,
        "tabs": view.subsystem_tabs(stef, name),
        "tool": tool,
        "up": view.is_up(sub) if sub else False,
        "log_sources": _log_sources(),
        "run_of": RUNS.of,
        "gate_of": (lambda item: view.gate(item, sub)) if sub else (lambda item: None),
        "fields_for": lambda item: view.fields_of(item, OPTIONS.warm),
        "worst_of": lambda items: render.worst_of(items, name or ""),
        "oob": False,
    }


def _link_context(name: str, tool: str, **extra: Any) -> dict[str, Any]:
    held = _board(name, tool)
    sub = held["sub"]
    opening = view.connect_routine(sub) if sub else None
    held.update(
        connect_fields=view.fields_of(opening, OPTIONS.warm) if opening else (),
        connect_values=bench_api.blank_values(opening.inputs) if opening else {},
        prelink=view.prelink_routines(sub) if sub else [],
        reason=None,
        error=None,
        known=held["up"] or opening is None,
    )
    held.update(extra)
    return held


def _calls_context(name: str, group: str | None, key: str | None) -> dict[str, Any]:
    held = _board(name, "calls")
    sub = held["sub"]
    groups = view.call_groups(sub) if sub else []
    held["groups"] = groups
    if not groups:
        return held
    names = [one for one, _ in groups]
    chosen = group if group in names else names[0]
    siblings = dict(groups)[chosen]
    picked = next((one for one in siblings if f"{one.group}.{one.name}" == key), None)
    routine = picked or siblings[0]
    held.update(
        siblings=siblings,
        routine=routine,
        fields=view.fields_of(routine, OPTIONS.warm),
        blank=bench_api.blank_values(routine.inputs),
    )
    return held


def _context(name: str | None, tool: str) -> dict[str, Any]:
    if tool == "routines":
        held = _board(name, tool)
        sub = held["sub"]
        held["groups"] = view.bench_groups(sub) if sub else []
        return held
    if tool == "calls":
        return _calls_context(name or "", None, None)
    return _link_context(name or "", "link") if name else _board(name, tool)


def _page(request: Request, name: str | None, tool: str) -> Any:
    held = _context(name, tool)
    partial = request.headers.get("hx-request") == "true"
    return templates.TemplateResponse(
        request, "diagnostics/main.html" if partial else "diagnostics/index.html", held
    )


def _fragment(request: Request, template: str, held: dict[str, Any]) -> Any:
    return templates.TemplateResponse(request, template, held)


@app.get("/diagnostics/stream/log")
async def log_stream() -> StreamingResponse:
    return _served(stream, "record", _log_html)


@app.get("/diagnostics/stream/runs")
async def run_stream() -> StreamingResponse:
    return _served(runs, "run", _run_html)


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> Any:
    return _page(request, view.first_available(stef), "link")


@app.get("/diagnostics/{name}/calls/panel", response_class=HTMLResponse)
def calls_panel(request: Request, name: str, group: str | None = None) -> Any:
    subsystem_of(name)
    return _fragment(
        request, "diagnostics/calls/panel.html", _calls_context(name, group, None)
    )


@app.get("/diagnostics/{name}/calls/method", response_class=HTMLResponse)
def calls_method(request: Request, name: str, key: str | None = None) -> Any:
    subsystem_of(name)
    group = key.rpartition(".")[0] if key else None
    return _fragment(
        request, "diagnostics/calls/method.html", _calls_context(name, group, key)
    )


@app.post("/diagnostics/{name}/calls/{key}/run", response_class=HTMLResponse)
async def calls_run(request: Request, name: str, key: str) -> Any:
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    declared = record.bench.routines[key]
    verdict = bench_api.readiness_of(declared, record.link_state)
    held = _calls_context(name, declared.group, key)
    if not verdict:
        held["answer"] = {"ok": False, "reason": str(verdict), "value": None}
        return _fragment(request, "diagnostics/calls/reply.html", held)
    taken = values_from(declared.inputs, await request.form())
    held["answer"] = await _called(name, key, declared, taken)
    return _fragment(request, "diagnostics/calls/reply.html", held)


@app.get("/diagnostics/{name}/options/{key}/{input_name}", response_class=HTMLResponse)
async def options_html(
    request: Request, name: str, key: str, input_name: str, refresh: int = 0
) -> Any:
    try:
        offered = await asyncio.to_thread(
            OPTIONS.fetch, name, key, input_name, bool(refresh)
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
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    declared = record.bench.routines[key]
    spec = next(
        (
            one
            for one in view.fields_of(declared, OPTIONS.warm)
            if one.name == input_name
        ),
        None,
    )
    if spec is None:
        raise HTTPException(404, f"{declared.id} declares no group {input_name!r}")
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
    declared = _link_of(name, "connect")
    form = await request.form()
    if _options_pending(declared.inputs, form):
        return _fragment(
            request,
            "diagnostics/link/actions.html",
            _link_context(name, "link", known=False),
        )
    taken = values_from(declared.inputs, form)
    try:
        verdict = await asyncio.to_thread(
            lambda: bench_api.readiness_with(declared, taken)
        )
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
    declared = _link_of(name, "connect")
    taken = values_from(declared.inputs, await request.form())
    error = None
    try:
        await _opened(name, declared, taken)
    except Busy as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        error = _failed(name, exc)
    held = _link_context(name, "link", error=error, known=True)
    return _fragment(request, "diagnostics/main.html", held)


@app.post("/diagnostics/{name}/link/disconnect", response_class=HTMLResponse)
async def disconnect_html(request: Request, name: str) -> Any:
    declared = _link_of(name, "disconnect")
    error = None
    try:
        await _closed(name, declared)
    except Exception as exc:  # noqa: BLE001
        error = _failed(name, exc)
    return _fragment(
        request, "diagnostics/main.html", _link_context(name, "link", error=error)
    )


@app.post("/diagnostics/{name}/routines/{key}/run", response_class=HTMLResponse)
async def routines_run(request: Request, name: str, key: str) -> Any:
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    declared = record.bench.routines[key]
    taken = values_from(declared.inputs, await request.form())
    _begin(name, key, taken)
    return _fragment(
        request, "diagnostics/routines/steps.html", _run_context(name, key)
    )


@app.get("/diagnostics/{name}", response_class=HTMLResponse)
def diagnostics_for(request: Request, name: str) -> Any:
    subsystem_of(name)
    return _page(request, name, "link")


@app.get("/diagnostics/{name}/{tool}", response_class=HTMLResponse)
def diagnostics_tool(request: Request, name: str, tool: str) -> Any:
    subsystem_of(name)
    return _page(request, name, tool if tool in view.TOOLS else "link")


def _run_context(name: str, key: str, oob: bool = False) -> dict[str, Any]:
    held = _board(name, "routines")
    declared = stef.subsystem(name).bench.routines[key]
    address = address_of(name, key)
    held.update(
        routine=declared,
        uid=render.slug(address),
        run=RUNS.of(address),
        oob=oob,
    )
    return held


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
    if not key or record.source not in stef.subsystems:
        return ": keep-alive\n\n"
    if key not in stef.subsystem(record.source).bench.routines:
        return ": keep-alive\n\n"
    held = _run_context(record.source, key, oob=True)
    body = _render("diagnostics/routines/head.html", held) + _render(
        "diagnostics/routines/steps.html", held
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
