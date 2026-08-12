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


def test_a_property_asking_to_be_walked_as_a_field_is_in_the_json(oven):
    packed = bench_api.as_json(oven)

    assert packed["id"] == "fixture"
    assert packed["summary"].startswith("An oven")


def test_a_plain_property_stays_behind(oven):
    assert "package" not in bench_api.as_json(oven)


def test_the_module_a_subsystem_reads_its_state_from_never_crosses(oven):
    assert "module" not in bench_api.as_json(oven)


# ── What never crosses ───────────────────────────────────────────────────────


def test_the_callable_that_runs_a_routine_never_crosses(oven):
    packed = routine_of(oven, "routines.ramp")

    assert "run" not in packed
    assert "precondition" not in packed
    assert "may_run" not in packed


def test_a_live_option_list_crosses_as_the_name_to_ask_for_it_by(oven):
    port = routine_of(oven, "routines.connect")["inputs"][0]

    assert port["options_name"] == "ports"
    assert port["options"] is None


def test_a_fixed_option_list_crosses_inline_since_it_cannot_move(oven):
    element = routine_of(oven, "routines.derived_form")["inputs"][0]

    assert element["options_name"] is None
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


def test_a_live_list_is_reachable_by_the_name_it_crossed_under(oven):
    assert bench_api.options_named("ports") == [
        {"value": "/dev/oven0", "label": "oven, front"}
    ]


def test_a_name_nothing_declares_is_a_refusal(oven):
    with pytest.raises(KeyError):
        bench_api.options_named("nothing_declares_this")
