"""What crosses to the browser, and what the browser is not allowed to do."""

import dataclasses
import json
import time

import pytest
from fastapi.testclient import TestClient

from gui.src.app import app
from shared import paths


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Return a client against the real app, logging to a state directory of its own."""
    with pytest.MonkeyPatch.context() as elsewhere:
        elsewhere.setenv(paths.ENV_HOME, str(tmp_path_factory.mktemp("home")))
        with TestClient(app) as started:
            yield started


@pytest.fixture
def unplugged(monkeypatch):
    """Answer as a machine with nothing attached, so a run settles the same anywhere."""
    from transport import fw

    monkeypatch.setattr(fw.probe, "candidates", lambda: ())


# ── What crosses ─────────────────────────────────────────────────────────────


def test_the_screen_renders_without_asking_any_subsystem_anything(client):
    page = client.get("/diagnostics")
    assert page.status_code == 200
    assert "STEF" in page.text


def declared_needing(payload, needs):
    """Return one subsystem's tests that need the link in one state."""
    return [t for t in payload["tests"] if t["needs"] == needs]


def transport_of(client):
    subsystems = client.get("/api/subsystems").json()
    return next(s for s in subsystems if s["id"] == "transport")


def command_named(payload, key):
    return next(c for c in payload["commands"] if c["key"] == key)


def test_every_declaration_reaches_the_browser_as_json(client):
    transport = transport_of(client)
    assert transport["link"]["target"]["name"] == "port"
    assert {t["key"] for t in declared_needing(transport, "down")} == {
        "prelink.VerifyPort",
        "prelink.FlashBoard",
    }


def test_a_live_option_list_crosses_undrawn_and_says_where_to_ask_for_it(client):
    port = transport_of(client)["link"]["target"]
    assert port["options"] is None
    assert port["reload"] == ["transport", "link", "port"]
    assert client.get("/api/options/transport/link/port").status_code == 200


def test_options_nobody_declared_are_a_refusal(client):
    assert client.get("/api/options/transport/link/nope").status_code == 404


def test_a_live_list_a_group_column_declares_is_reachable_by_its_name(
    client, monkeypatch
):
    # A column is drawn by the code that draws a top-level control, so it fetches
    # the same way, and a walk that stopped at the top would 404 what it asked for.
    from gui.src.app import subsystem_of
    from shared.subsystem import choice, group

    sub = subsystem_of("transport")
    declared = sub.command("raw.write")
    column = choice("gear", lambda sub: ("high", "low"))
    patched = dataclasses.replace(
        declared, inputs=(*declared.inputs, group("rows", columns=(column,)))
    )
    monkeypatch.setattr(
        type(sub),
        "commands",
        tuple(patched if one is declared else one for one in type(sub).commands),
    )
    offered = client.get("/api/options/transport/raw.write/gear")
    assert offered.status_code == 200
    assert [one["value"] for one in offered.json()] == ["high", "low"]


def test_the_port_list_offers_more_than_the_shortlist(client):
    offered = client.get("/api/options/transport/link/port").json()
    assert offered[0]["value"] == "auto"
    assert all("value" in one and "label" in one for one in offered)


def test_a_derived_form_keeps_the_shape_the_firmware_declared(client):
    write = command_named(transport_of(client), "raw.write")
    ops = next(p for p in write["inputs"] if p["kind"] == "group")
    assert {c["name"] for c in ops["columns"]} == {"reg", "value"}


def test_a_command_crosses_carrying_the_address_every_route_takes(client):
    write = command_named(transport_of(client), "raw.write")
    assert (write["group"], write["name"]) == ("raw", "write")
    assert write["hazard"] == "writes driver registers"


def test_a_test_crosses_with_its_steps_and_its_end(client):
    one_turn = next(
        t for t in transport_of(client)["tests"] if t["key"] == "spin.OneTurn"
    )
    assert one_turn["hazardous"] is True
    assert one_turn["steps"][0]["title"] == "Identify"
    assert one_turn["end"]["title"] == "At rest"


def test_nothing_that_crosses_can_be_spelled_in_ctypes(client):
    payload = client.get("/api/subsystems").json()
    assert json.loads(json.dumps(payload)) == payload


# ── Gating ───────────────────────────────────────────────────────────────────


def test_connecting_is_refused_with_the_sentence_the_probe_produced(client, unplugged):
    verdict = client.post("/api/link/transport/readiness", json={"port": "auto"}).json()
    assert verdict["ok"] is False
    assert verdict["reason"]


def test_a_call_on_a_link_that_is_down_is_refused_by_its_precondition(client):
    answer = client.post("/api/call/transport/sys.version", json={})
    assert answer.status_code == 409
    assert "not connected" in answer.json()["detail"]


def test_a_call_nobody_declared_is_a_refusal(client):
    assert client.post("/api/call/transport/no.such", json={}).status_code == 404


def test_a_test_nobody_declared_is_a_refusal(client):
    assert client.post("/api/run/transport/no_such_test", json={}).status_code == 404


def test_a_test_that_opens_the_port_is_refused_while_the_link_holds_it(
    client, monkeypatch
):
    # Two owners of one serial port is a corrupted exchange rather than an
    # error, so this has to be refused rather than attempted.
    from gui.src.app import stef
    from shared.subsystem import LinkState

    sub = stef.subsystem("transport")
    monkeypatch.setattr(sub, "link_state", lambda: LinkState.UP)
    answer = client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    assert answer.status_code == 409
    assert "disconnect first" in answer.json()["detail"]


def test_stopping_a_subsystem_that_is_not_connected_says_why(client):
    answer = client.post("/api/stop/transport").json()
    assert answer["ok"] is False
    assert "not sent" in answer["reason"]


def test_answering_when_nothing_is_asked_is_refused(client):
    assert client.post("/api/answer/transport", json={"value": True}).status_code == 409


# ── Running ──────────────────────────────────────────────────────────────────


def outcomes(timeout=5.0):
    from gui.src.app import runs

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(record.kind == "done" for record in runs._backlog):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("the run never ended")
    return [
        record.data["outcome"] for record in runs._backlog if record.kind == "outcome"
    ]


def test_a_run_reports_one_outcome_per_step_as_it_reaches_it(client, unplugged):
    answer = client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    assert answer.status_code == 200
    settled = outcomes()
    assert len(settled) == 3
    assert settled[0]["status"] == "failed"


def test_a_run_says_it_started_before_it_says_anything_it_produced(client, unplugged):
    from gui.src.app import runs

    client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    outcomes()
    assert [record.kind for record in runs._backlog][0] == "started"


def test_a_run_s_verdict_is_the_worst_step_it_produced(client, unplugged):
    from gui.src.app import runs

    client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    outcomes()
    (ended,) = [record for record in runs._backlog if record.kind == "done"]
    assert ended.data["status"] == "failed"


def test_a_step_with_nothing_to_report_writes_no_log_line(client, unplugged):
    from gui.src.app import stream

    before = len(stream._backlog)
    client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    outcomes()
    written = stream._backlog[before:]
    assert written
    assert all(record.text for record in written)


def test_a_failure_leaves_the_steps_after_it_skipped_as_not_reached(client, unplugged):
    client.post("/api/run/transport/prelink.VerifyPort", json={"port": "auto"})
    settled = outcomes()
    assert [s["status"] for s in settled[1:]] == ["skipped", "skipped"]
    assert [s["skipped"] for s in settled[1:]] == ["not_reached", "not_reached"]


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
    from shared.diagnostics import as_json
    from shared.subsystem import READY, blocked

    assert as_json(READY) == {"ok": True, "reason": None}
    assert as_json(blocked("no")) == {"ok": False, "reason": "no"}


def test_a_tool_that_needs_the_link_sends_you_back_to_link_while_it_is_down(client):
    page = client.get("/diagnostics/transport/tests", follow_redirects=False)
    assert page.status_code == 307
    assert page.headers["location"] == "/diagnostics/transport"
