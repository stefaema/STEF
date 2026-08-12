import json

import pytest

from shared import bench_api
from shared.bench_api import Level, Result, StepOutcome, Table


def routine_of(oven, key):
    """Return one routine as the screen receives it."""
    return bench_api.routine_json(oven.routines[key], oven.now())


# ── One convention, not one function per record ──────────────────────────────


def test_a_whole_subsystem_survives_being_json(oven):
    assert json.dumps(bench_api.subsystem_json(oven))


def test_an_enum_crosses_as_its_value():
    assert bench_api.as_json(Level.WARN) == "warn"


def test_bytes_cross_as_the_hex_a_datasheet_writes():
    assert bench_api.as_json(Result(Level.OK, "s", raw=b"\x0a\xff"))["raw"] == "0a ff"


def test_a_nested_record_crosses_as_an_object():
    packed = bench_api.as_json(
        Result(Level.OK, "s", table=Table(head=("a",), rows=(("1",),)))
    )

    assert packed["table"] == {"head": ["a"], "rows": [["1"]]}


def test_an_outcome_carries_its_step_and_whatever_it_found():
    packed = bench_api.as_json(
        StepOutcome(bench_api.PASSED, "held", Result(Level.OK, "s"), step="Holding")
    )

    assert packed["status"] == "passed"
    assert packed["step"] == "Holding"
    assert packed["value"]["summary"] == "s"


def test_what_a_record_does_is_left_out_and_what_it_holds_is_not(oven):
    packed = bench_api.as_json(oven.routines["routines.connect"])

    assert "do" not in packed
    assert packed["title"] == "Connect"


def test_the_module_a_subsystem_reads_its_state_from_never_crosses(oven):
    assert "module" not in bench_api.as_json(oven)


def test_the_name_a_subsystem_is_known_by_reaches_the_screen(oven):
    assert bench_api.subsystem_json(oven)["id"] == "fixture"


# ── What never crosses ───────────────────────────────────────────────────────


def test_the_callable_that_runs_a_routine_never_crosses(oven):
    packed = routine_of(oven, "routines.ramp")

    assert "do" not in packed


def test_a_live_list_arrives_drawn_and_carrying_where_to_ask_again(oven):
    port = routine_of(oven, "routines.connect")["inputs"][0]

    assert port["options"] == [{"value": "/dev/oven0", "label": "oven, front"}]
    assert port["reload"] == "/api/options/fixture/routines.connect/port"


def test_a_fixed_list_is_drawn_and_never_asked_for_again(oven):
    element = routine_of(oven, "routines.derived_form")["inputs"][0]

    assert element["reload"] is None
    assert element["options"] == [
        {"value": 0, "label": "UPPER"},
        {"value": 1, "label": "LOWER"},
    ]


def test_a_group_s_columns_cross_as_controls_too(oven):
    steps = routine_of(oven, "routines.derived_form")["inputs"][-1]

    assert [column["name"] for column in steps["columns"]] == ["celsius", "minutes"]


# ── What a screen needs that the record does not hold ────────────────────────


def test_a_routine_arrives_carrying_its_own_verdict(oven):
    assert routine_of(oven, "routines.ramp")["ready"] == {
        "ok": False,
        "reason": "not connected",
    }


def test_the_same_routine_arrives_ready_once_the_link_is_up(linked):
    assert routine_of(linked, "routines.ramp")["ready"]["ok"]


def test_a_routine_says_whether_it_wants_asking_before_it_runs(oven):
    assert routine_of(oven, "routines.connect")["asks_first"]
    assert not routine_of(oven, "routines.ramp")["asks_first"]


def test_the_form_arrives_with_what_it_starts_at(oven):
    assert routine_of(oven, "generated.ramp_once")["blank"] == {"celsius": 0}


def test_the_state_is_read_once_for_the_whole_subsystem(oven):
    packed = bench_api.subsystem_json(oven)

    assert packed["state"] == "down"
    assert all(r["ready"]["reason"] != "" for r in packed["routines"])


# ── A list nobody could send ahead of time ───────────────────────────────────


def test_a_control_is_asked_again_by_where_it_lives(oven):
    assert bench_api.options_of("fixture", "routines.connect", "port") == [
        {"value": "/dev/oven0", "label": "oven, front"}
    ]


def test_an_input_the_routine_does_not_declare_is_a_refusal(oven):
    with pytest.raises(KeyError):
        bench_api.options_of("fixture", "routines.connect", "nothing_declares_this")


def test_two_controls_sharing_a_live_list_ask_for_it_once():
    seen = []

    def ports():
        seen.append(1)
        return ("/dev/oven0",)

    asked = {}
    bench_api.input_json(bench_api.choice("a", ports), None, asked)
    bench_api.input_json(bench_api.choice("b", ports), None, asked)

    assert len(seen) == 1


def test_a_control_outside_a_payload_still_draws_its_own_options():
    def ports():
        return ("/dev/oven0",)

    drawn = bench_api.input_json(bench_api.choice("port", ports))

    assert drawn["options"] == [{"value": "/dev/oven0", "label": "/dev/oven0"}]
    assert drawn["reload"] is None
