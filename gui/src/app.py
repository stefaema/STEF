"""The backend: it reads the registry, serialises it, and runs what is asked of it.

It knows no subsystem. Every route below is written against the contract's own
words, so a subsystem that has not been written yet will render the day someone
decorates it, and this file will not change when they do.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gui.src import text
from gui.src.i18n import gettext, ngettext
from gui.src.runner import Record, Stream, call_off_loop, stream_run
from machine import Activity, Busy, Machine, subsystem_json
from shared import bench_api, logs

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
HEARTBEAT = 15.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Import every declaration before the first request can ask for one."""
    wake()
    yield


app = FastAPI(title="STEF", lifespan=lifespan)
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_gettext_callables(gettext, ngettext, newstyle=True)  # pyright: ignore[reportAttributeAccessIssue]

stream = Stream()
stef = Machine()
log = logs.component("gui")


def wake() -> None:
    """Put logging up, then assemble the machine.

    A declaration runs when its module is imported, so assembling is the
    registration and skipping it leaves a subsystem that silently does not
    appear. Logging goes up first so an import that fails says why.
    """
    written = logs.start()
    logs.to(stream.sink)
    log.info("writing to {}", written)
    stef.assemble()
    stream.say("gui", "ok", "gui", gettext("Backend ready"))


def subsystem_of(name: str) -> Any:
    """Return one assembled subsystem, or say there is no such thing."""
    try:
        return stef.subsystem(name)
    except KeyError:
        raise HTTPException(404, f"no subsystem {name!r}") from None


def _running(what: str) -> str:
    """Return the sentence anything refused while this runs is told."""
    return gettext("{what} is running").format(what=what)


def _failed(name: str, exc: BaseException) -> str:
    """Log what went wrong in full, and return the one line a control shows.

    A type and a message name the failure without saying where it happened, and
    a subsystem that fails once in an operator's hands is a subsystem nobody can
    debug afterwards.
    """
    message = f"{type(exc).__name__}: {exc}"
    stream.say(name, "error", "result", message)
    stream.say(name, "error", "traceback", "".join(traceback.format_exception(exc)))
    return message


def _link_state(name: str) -> str:
    """Return what a subsystem is doing, asked of its package rather than remembered."""
    return stef.link_state_of(name).value


# ── The screen ───────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """Send an operator to the only screen that is served."""
    return RedirectResponse("/diagnostics")


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> Any:
    """Render the one screen, which fills itself in from the API."""
    return templates.TemplateResponse(
        request,
        "diagnostics.html",
        {"subsystems": list(stef.roster), "text": text.catalog()},
    )


# ── What is declared ─────────────────────────────────────────────────────────


@app.get("/api/state")
def machine_state() -> dict[str, Any]:
    """Return what the machine is doing and what each subsystem is doing."""
    return {
        "state": stef.activity.value,
        "busy": stef.busy_with,
        "areas": stef.openings(),
        "subsystems": {name: _link_state(name) for name in stef.subsystems},
    }


@app.get("/api/subsystems")
def declarations() -> list[dict[str, Any]]:
    """Return every part of the machine, declared or merely expected.

    One that nothing declared crosses as a name and nothing else, which is
    honest: the part exists, and this build cannot reach it.
    """
    found = []
    for name in stef.roster:
        if name not in stef.subsystems:
            found.append({"id": name, "available": False})
            continue
        found.append({**subsystem_json(stef.subsystem(name)), "available": True})
    return found


@app.get("/api/options/{name}/{key}/{input_name}")
async def options_for(name: str, key: str, input_name: str) -> list[dict[str, Any]]:
    """Return one control's options, fetched afresh because the world moves.

    Off the loop, since a list may come from the hardware rather than from here.
    """
    try:
        return await asyncio.to_thread(bench_api.options_of, name, key, input_name)
    except KeyError as exc:
        raise HTTPException(404, f"no options for {name}.{key}.{input_name}") from exc


# ── The link ─────────────────────────────────────────────────────────────────


def _link_of(name: str, which: str) -> Any:
    """Return one of a subsystem's link routines, or say it declares none."""
    found = bench_api.link_routine(subsystem_of(name).bench, which)
    if found is None:
        raise HTTPException(404, f"{name} declares no {which}")
    return found


@app.post("/api/link/{name}/readiness")
async def link_readiness(name: str, values: dict[str, Any]) -> dict[str, Any]:
    """Say whether connecting may proceed, and why not when it may not.

    Answered by asking rather than by remembering whether a panel was run, since
    a remembered answer goes stale on the next replug.
    """
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
    """Open the link, atomically, and say how it went."""
    declared = _link_of(name, "connect")
    taken = bench_api.coerced_values(declared.inputs, values)
    shown = ", ".join(f"{k}={v!r}" for k, v in taken.items())
    stream.say(name, "ok", "command", f"connect({shown})")
    try:
        await call_off_loop(
            stef,
            Activity.BENCHING,
            f"{name}.connect",
            _running(f"{name}.connect"),
            lambda: _settle(declared, taken),
        )
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    stream.say(name, "ok", "result", gettext("Connected"))
    return {"ok": True, "reason": None, "link": _link_state(name)}


@app.post("/api/link/{name}/disconnect")
async def disconnect(name: str) -> dict[str, Any]:
    """Close the link and everything it started."""
    declared = _link_of(name, "disconnect")
    stream.say(name, "ok", "command", "disconnect()")
    try:
        await asyncio.to_thread(lambda: _settle(declared, {}))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": _failed(name, exc), "link": _link_state(name)}
    stream.say(name, "ok", "result", gettext("Disconnected"))
    return {"ok": True, "link": _link_state(name)}


def _settle(declared: Any, values: dict[str, Any]) -> None:
    """Run a one-step routine to the end, raising whatever it reported as a failure."""
    for outcome in bench_api.run_routine(declared, values):
        if outcome.status is bench_api.FAILED:
            raise RuntimeError(outcome.detail)


# ── Running a routine ────────────────────────────────────────────────────────


@app.post("/api/run/{name}/{test_id}")
async def run(name: str, test_id: str, values: dict[str, Any]) -> StreamingResponse:
    """Run one routine, streaming each step's outcome as the run reaches it."""
    record = subsystem_of(name)
    if test_id not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{test_id}")
    test = record.bench.routines[test_id]
    verdict = bench_api.readiness_of(test, record.link_state)
    if not verdict:
        raise HTTPException(409, str(verdict))
    taken = bench_api.coerced_values(test.inputs, values)

    shown = ", ".join(f"{k}={v!r}" for k, v in taken.items())
    stream.say(name, "ok", "command", f"{test_id}({shown})")

    async def body() -> AsyncIterator[str]:
        try:
            produced = stream_run(
                stef,
                Activity.BENCHING,
                f"{name}.{test_id}",
                _running(f"{name}.{test_id}"),
                lambda: bench_api.run_routine(test, taken),
            )
            async for item in produced:
                packed = (
                    item if isinstance(item, dict) else bench_api.outcome_json(item)
                )
                yield _sse("outcome", packed)
        except Busy as exc:
            yield _sse("refused", {"reason": str(exc)})
            return
        yield _sse("done", {})

    return StreamingResponse(body(), media_type="text/event-stream")


def _one_result(declared: Any, values: dict[str, Any]) -> Any:
    """Return what a single-step routine found, which is what a call used to return."""
    settled = list(bench_api.run_routine(declared, values))
    failed = next((o for o in settled if o.status is bench_api.FAILED), None)
    if failed is not None:
        raise RuntimeError(failed.detail)
    return next((o.value for o in settled if o.value is not None), None)


@app.post("/api/call/{name}/{key:path}")
async def call(name: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
    """Make one call by hand, and return what it found."""
    record = subsystem_of(name)
    if key not in record.bench.routines:
        raise HTTPException(404, f"no routine {name}.{key}")
    declared = record.bench.routines[key]

    verdict = bench_api.readiness_of(declared, record.link_state)
    if not verdict:
        raise HTTPException(409, str(verdict))

    taken = bench_api.coerced_values(declared.inputs, values)
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
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        message = _failed(name, exc)
        return {"ok": False, "reason": message, "value": None}

    packed = bench_api.result_json(answer) if answer is not None else None
    stream.say(name, "ok", "result", packed["summary"] if packed else key)
    return {"ok": True, "reason": None, "value": packed}


# ── The stream everything reports on ─────────────────────────────────────────


def _sse(event: str, data: Any) -> str:
    """Return one server-sent event, which is the whole of the wire format."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/events")
async def events() -> StreamingResponse:
    """Stream every record, catching a late listener up on what it missed."""
    listener, backlog = stream.listen()

    async def body() -> AsyncIterator[str]:
        try:
            for record in backlog:
                yield _sse("record", record.payload())
            while True:
                try:
                    record = await asyncio.to_thread(listener.get, True, HEARTBEAT)
                except Exception:  # noqa: BLE001
                    yield ": keep-alive\n\n"
                    continue
                yield _sse("record", record.payload())
        finally:
            stream.drop(listener)

    return StreamingResponse(body(), media_type="text/event-stream")


app.mount("/web", StaticFiles(directory=str(WEB)), name="web")

__all__ = ["Activity", "Record", "app", "stef", "stream"]
