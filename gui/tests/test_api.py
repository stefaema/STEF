"""What crosses to the browser, and what the browser is not allowed to do."""

import json

import pytest
from fastapi.testclient import TestClient

from gui.src import wire
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
    assert {t["id"] for t in transport["link_tests"]} == {"verify_port", "flash_board"}
    assert len(transport["actions"]) == 26


def test_a_live_option_list_crosses_as_its_name_and_not_as_a_snapshot(client):
    transport = client.get("/api/subsystems").json()[0]
    port = transport["link"]["params"][0]
    assert port["catalog"] == "serial_ports"
    assert port["options"] is None
    assert client.get("/api/catalog/serial_ports").status_code == 200


def test_a_catalog_nobody_declared_is_a_refusal(client):
    assert client.get("/api/catalog/nothing_declares_this").status_code == 404


def test_an_option_may_read_differently_from_what_the_call_takes():
    assert wire._option(("/dev/ttyACM0", "/dev/ttyACM0 (a board)")) == {
        "value": "/dev/ttyACM0",
        "label": "/dev/ttyACM0 (a board)",
    }
    assert wire._option("auto") == {"value": "auto", "label": "auto"}


def test_the_port_list_offers_more_than_the_shortlist(client):
    offered = client.get("/api/catalog/serial_ports").json()
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


def test_a_bench_test_nobody_declared_is_a_refusal(client):
    assert client.post("/api/run/transport/no_such_test", json={}).status_code == 404


def test_a_routine_that_opens_the_port_is_refused_while_the_link_holds_it(
    client, monkeypatch
):
    # Two owners of one serial port is a corrupted exchange rather than an
    # error, so this has to be refused rather than attempted.
    from gui.src import app as backend

    monkeypatch.setitem(backend.subsystems, "transport", _Up())
    answer = client.post("/api/run/transport/verify_port", json={"port": "auto"})
    assert answer.status_code == 409
    assert "Disconnect first" in answer.json()["detail"]


class _Up:
    """A subsystem reporting a link that is up, without one being open."""

    class state:
        value = "up"


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
    answer = client.post("/api/run/transport/verify_port", json={"port": "auto"})
    assert answer.status_code == 200
    settled = outcomes(answer.text)
    assert len(settled) == 3
    assert settled[0]["status"] == "failed"


def test_a_step_with_nothing_to_report_writes_no_log_line(client, unplugged):
    from gui.src.app import stream

    before = len(stream._backlog)
    client.post("/api/run/transport/verify_port", json={"port": "auto"})
    written = stream._backlog[before:]
    assert written
    assert all(record.text for record in written)


def test_abandoning_leaves_the_steps_after_it_skipped_rather_than_failed(
    client, unplugged
):
    settled = outcomes(
        client.post("/api/run/transport/verify_port", json={"port": "auto"}).text
    )
    assert [s["status"] for s in settled[1:]] == ["skipped", "skipped"]


# ── Coercion, since JSON has one number type and no bytes ────────────────────


def test_hex_typed_into_a_raw_field_becomes_bytes():
    from shared.bench_api import Kind, Param

    field = Param(name="tx", kind=Kind.RAW_BYTES)
    assert wire.arguments((field,), {"tx": "de ad be ef"}) == {
        "tx": b"\xde\xad\xbe\xef"
    }
    assert wire.arguments((field,), {"tx": ""}) == {"tx": b""}


def test_an_odd_number_of_hex_digits_is_read_as_a_leading_zero():
    from shared.bench_api import Kind, Param

    field = Param(name="tx", kind=Kind.RAW_BYTES)
    assert wire.arguments((field,), {"tx": "f0f"}) == {"tx": b"\x0f\x0f"}


def test_something_that_is_not_hex_is_refused_rather_than_sent():
    from shared.bench_api import Kind, Param

    field = Param(name="tx", kind=Kind.RAW_BYTES)
    with pytest.raises(ValueError, match="hexadecimal"):
        wire.arguments((field,), {"tx": "zz"})


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
    from shared.bench_api import READY, blocked

    assert wire.readiness(READY) == {"ok": True, "reason": None}
    assert wire.readiness(blocked("no")) == {"ok": False, "reason": "no"}
    assert wire.readiness(None) == {"ok": False, "reason": None}
