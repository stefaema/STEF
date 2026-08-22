import pytest

from shared import bench_api
from shared.bench_api import Level, Result, StepOutcome, Table
from shared.bench_api.tests.fixture import state


def routine_of(oven, key):
    """Return one routine as the screen receives it."""
    return bench_api.routine_json(oven.routines[key], state())


# ── One function per record ──────────────────────────────────────────────────


def test_a_level_crosses_as_its_value():
    assert bench_api.result_json(Result(Level.WARN, "s"))["level"] == "warn"


def test_bytes_cross_as_the_hex_a_datasheet_writes():
    packed = bench_api.result_json(Result(Level.OK, "s", raw=b"\x0a\xff"))

    assert packed["raw"] == "0a ff"


def test_a_table_crosses_as_its_heading_and_its_rows():
    packed = bench_api.result_json(
        Result(Level.OK, "s", table=Table(head=("a",), rows=(("1",),)))
    )

    assert packed["table"] == {"head": ["a"], "rows": [["1"]]}


def test_a_step_that_found_nothing_carries_no_panel():
    assert (
        bench_api.outcome_json(StepOutcome(bench_api.PASSED, "held"))["value"] is None
    )


def test_an_outcome_carries_its_step_and_whatever_it_found():
    packed = bench_api.outcome_json(
        StepOutcome(bench_api.PASSED, "held", Result(Level.OK, "s"), step="Holding")
    )

    assert packed["status"] == "passed"
    assert packed["step"] == "Holding"
    assert packed["value"]["summary"] == "s"


# ── What never crosses ───────────────────────────────────────────────────────


def test_the_callable_that_runs_a_routine_never_crosses(oven):
    packed = routine_of(oven, "routines.ramp")

    assert "do" not in packed
    assert packed["title"] == "Ramp the oven"


def test_a_live_list_crosses_undrawn_and_carrying_where_to_ask_for_it(oven):
    port = routine_of(oven, "routines.connect")["inputs"][0]

    assert port["options"] is None
    assert port["reload"] == "/api/options/fixture/routines.connect/port"


def test_a_form_starts_a_live_control_at_nothing(oven):
    assert routine_of(oven, "routines.connect")["blank"] == {"port": None}


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


def test_a_verdict_nobody_reached_disables_rather_than_enables():
    assert bench_api.readiness_json(None) == {"ok": False, "reason": None}


def test_a_routine_says_whether_it_wants_asking_before_it_runs(oven):
    assert routine_of(oven, "routines.connect")["asks_first"]
    assert not routine_of(oven, "routines.ramp")["asks_first"]


def test_the_form_arrives_with_what_it_starts_at(oven):
    assert routine_of(oven, "generated.ramp_once")["blank"] == {"celsius": 0}


# ── A list nobody could send ahead of time ───────────────────────────────────


def test_a_control_is_asked_again_by_where_it_lives(oven):
    assert bench_api.options_of("fixture", "routines.connect", "port") == [
        {"value": "/dev/oven0", "label": "oven, front"}
    ]


def test_an_input_the_routine_does_not_declare_is_a_refusal(oven):
    with pytest.raises(KeyError):
        bench_api.options_of("fixture", "routines.connect", "nothing_declares_this")


def test_building_a_payload_never_calls_a_live_list(oven):
    # The board answers a live list, so a payload that resolved one would put a
    # round trip behind every page load and every poll.
    seen = []

    def ports():
        seen.append(1)
        return ("/dev/oven0",)

    bench_api.input_json(bench_api.choice("port", ports))

    assert seen == []
