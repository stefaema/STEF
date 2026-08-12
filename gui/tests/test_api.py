"""What crosses to the browser, and what the browser is not allowed to do."""

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from gui.src.app import app


@pytest.fixture(scope="module")
def client():
    """Return a client against the real app, declarations and all."""
    with TestClient(app) as started:
        yield started


@pytest.fixture
def unplugged(monkeypatch):
    """Answer as a machine with nothing attached, so a run settles the same anywhere."""
    from transport import fw_probe

    monkeypatch.setattr(fw_probe, "candidates", lambda: ())


# ── What crosses ─────────────────────────────────────────────────────────────


def test_the_screen_renders_without_asking_any_subsystem_anything(client):
    page = client.get("/diagnostics")
    assert page.status_code == 200
    assert "STEF" in page.text


def test_every_declaration_reaches_the_browser_as_json(client):
    subsystems = client.get("/api/subsystems").json()
    transport = next(s for s in subsystems if s["id"] == "transport")
    assert transport["link"]["params"][0]["name"] == "port"
    assert {t["id"] for t in transport["link_tests"]} == {
        "prelink.verify_port",
        "prelink.flash_board",
    }
    assert len(transport["actions"]) == 26


def test_a_live_option_list_crosses_undrawn_and_says_where_to_ask_for_it(client):
    transport = client.get("/api/subsystems").json()[0]
    port = transport["link"]["params"][0]
    assert port["options"] is None
    assert port["reload"] == "/api/options/transport/link.connect/port"
    assert client.get(port["reload"]).status_code == 200


def test_options_nobody_declared_are_a_refusal(client):
    assert client.get("/api/options/transport/link.connect/nope").status_code == 404


def test_a_live_list_a_group_column_declares_is_reachable_by_its_name(client):
    # A column is drawn by the code that draws a top-level control, so it fetches
    # the same way, and a walk that stopped at the top would 404 what it asked for.
    from shared import bench_api

    def gears():
        """Return what is on the shaft right now."""
        return ("high", "low")

    record = bench_api.REGISTRY.subsystem("transport")
    declared = record.routines["raw.write"]
    column = bench_api.choice("gear", gears)
    patched = (*declared.inputs, bench_api.group("rows", columns=(column,)))
    record.routines["raw.write"] = dataclasses.replace(declared, inputs=patched)
    try:
        offered = client.get("/api/options/transport/raw.write/gear")
        assert offered.status_code == 200
        assert [one["value"] for one in offered.json()] == ["high", "low"]
    finally:
        record.routines["raw.write"] = declared


def test_the_port_list_offers_more_than_the_shortlist(client):
    offered = client.get("/api/options/transport/link.connect/port").json()
    assert offered[0]["value"] == "auto"
    assert all("value" in one and "label" in one for one in offered)


def test_a_derived_form_keeps_the_shape_the_firmware_declared(client):
    transport = client.get("/api/subsystems").json()[0]
    write = next(a for a in transport["actions"] if a["name"] == "raw.write")
    ops = next(p for p in write["params"] if p["kind"] == "group")
    assert {c["name"] for c in ops["columns"]} == {"reg", "value"}


def test_nothing_that_crosses_can_be_spelled_in_ctypes(client):
    payload = client.get("/api/subsystems").json()
    assert json.loads(json.dumps(payload)) == payload


# ── Gating ───────────────────────────────────────────────────────────────────


def test_connecting_is_refused_with_the_sentence_the_probe_produced(client, unplugged):
    verdict = client.post("/api/link/transport/readiness", json={"port": "auto"}).json()
    assert verdict["ok"] is False
    assert verdict["reason"]


def test_an_action_on_a_link_that_is_down_is_refused_by_its_precondition(client):
    answer = client.post("/api/action/transport/sys.version", json={})
    assert answer.status_code == 409
    assert "not connected" in answer.json()["detail"]


def test_an_action_nobody_declared_is_a_refusal(client):
    assert client.post("/api/action/transport/no.such", json={}).status_code == 404


def test_a_routine_nobody_declared_is_a_refusal(client):
    assert client.post("/api/run/transport/no_such_test", json={}).status_code == 404


def test_a_routine_that_opens_the_port_is_refused_while_the_link_holds_it(
    client, monkeypatch
):
    # Two owners of one serial port is a corrupted exchange rather than an
    # error, so this has to be refused rather than attempted.
    from shared import bench_api
    from shared.bench_api import SubsystemState

    package = bench_api.REGISTRY.subsystem("transport").module
    monkeypatch.setattr(package, "state", lambda: SubsystemState.UP)
    answer = client.post(
        "/api/run/transport/prelink.verify_port", json={"port": "auto"}
    )
    assert answer.status_code == 409
    assert "disconnect first" in answer.json()["detail"]


# ── Running ──────────────────────────────────────────────────────────────────


def outcomes(text):
    """Return the outcomes out of one server-sent stream."""
    settled = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if lines.get("event") == "outcome":
            settled.append(json.loads(lines["data"]))
    return settled


def test_a_run_streams_one_outcome_per_step_as_it_reaches_it(client, unplugged):
    answer = client.post(
        "/api/run/transport/prelink.verify_port", json={"port": "auto"}
    )
    assert answer.status_code == 200
    settled = outcomes(answer.text)
    assert len(settled) == 3
    assert settled[0]["status"] == "failed"


def test_a_step_with_nothing_to_report_writes_no_log_line(client, unplugged):
    from gui.src.app import stream

    before = len(stream._backlog)
    client.post("/api/run/transport/prelink.verify_port", json={"port": "auto"})
    written = stream._backlog[before:]
    assert written
    assert all(record.text for record in written)


def test_abandoning_leaves_the_steps_after_it_skipped_rather_than_failed(
    client, unplugged
):
    settled = outcomes(
        client.post(
            "/api/run/transport/prelink.verify_port", json={"port": "auto"}
        ).text
    )
    assert [s["status"] for s in settled[1:]] == ["skipped", "skipped"]


def test_every_record_carries_a_number_that_only_goes_up():
    # A listener is handed the backlog again whenever it reconnects, so it needs
    # a way to tell a replayed record from a new one.
    from gui.src.runner import Stream

    said = Stream()
    said.say("rig", "ok", "gui", "one")
    said.say("rig", "ok", "gui", "two")
    listener, backlog = said.listen()
    assert [r.seq for r in backlog] == [1, 2]
    assert all(r.payload()["seq"] == r.seq for r in backlog)


def test_a_late_listener_is_caught_up_on_what_it_missed():
    from gui.src.runner import Stream

    said = Stream()
    said.say("rig", "ok", "gui", "before")
    _, backlog = said.listen()
    assert [r.text for r in backlog] == ["before"]


def test_a_readiness_crosses_as_its_verdict_and_its_reason():
    from shared import bench_api
    from shared.bench_api import READY, blocked

    assert bench_api.readiness_json(READY) == {"ok": True, "reason": None}
    assert bench_api.readiness_json(blocked("no")) == {"ok": False, "reason": "no"}
