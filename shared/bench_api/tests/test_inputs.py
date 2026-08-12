import pytest

from shared import bench_api
from shared.bench_api import Input
from shared.bench_api.tests.fixture.payloads import Element, RampArgs, Watched

# ── The inputs an annotated payload implies ──────────────────────────────────


def kinds_of(payload):
    """Return each derived input as name and kind."""
    return {item.name: item.kind for item in bench_api.inputs_for(payload)}


def test_each_field_becomes_the_one_kind_its_type_implies():
    assert kinds_of(RampArgs) == {
        "element": "choice",
        "celsius": "integer",
        "hold": "boolean",
        "watching": "bitmask",
        "seal": "raw_bytes",
        "steps": "group",
    }


def test_a_repeating_field_carries_its_own_columns():
    steps = next(i for i in bench_api.inputs_for(RampArgs) if i.name == "steps")

    assert [column.name for column in steps.columns] == ["celsius", "minutes"]


def test_the_prose_beside_a_field_becomes_the_control_s_hint():
    celsius = next(i for i in bench_api.inputs_for(RampArgs) if i.name == "celsius")

    assert celsius.hint == "where it settles"


def test_a_type_nobody_decided_how_to_draw_is_refused_by_field_name():
    from dataclasses import dataclass

    @dataclass
    class Odd:
        when: complex

    with pytest.raises(bench_api.DeclarationError, match="Odd.when"):
        bench_api.inputs_for(Odd)


def test_taking_no_payload_derives_no_form():
    assert bench_api.inputs_for(None) == ()


def test_an_override_replaces_one_field_and_leaves_the_rest_derived():
    derived = bench_api.inputs_for(RampArgs)
    mine = bench_api.choice("element", (0, 1))

    settled = bench_api.overridden(derived, {"element": mine})

    assert settled[0] is mine
    assert [item.name for item in settled] == [item.name for item in derived]


def test_an_override_naming_no_field_is_refused():
    with pytest.raises(bench_api.DeclarationError, match="name no such field"):
        bench_api.overridden(
            bench_api.inputs_for(RampArgs), {"kelvin": bench_api.integer("kelvin")}
        )


# ── What a declaration refuses ───────────────────────────────────────────────


def test_a_kind_no_control_renders_is_refused():
    with pytest.raises(bench_api.DeclarationError, match="which no control renders"):
        bench_api.checked_inputs([Input(name="celsius", kind="dial")])


def test_a_pick_one_with_nothing_to_pick_from_is_refused():
    with pytest.raises(bench_api.DeclarationError, match="needs options"):
        bench_api.checked_inputs([Input(name="element", kind="choice")])


def test_a_group_with_no_columns_is_refused():
    with pytest.raises(bench_api.DeclarationError, match="needs columns"):
        bench_api.checked_inputs([Input(name="steps", kind="group")])


def test_a_column_is_checked_the_way_a_control_is():
    with pytest.raises(bench_api.DeclarationError, match="which no control renders"):
        bench_api.checked_inputs(
            [bench_api.group("steps", columns=[Input(name="celsius", kind="dial")])]
        )


# ── What a blank form holds ──────────────────────────────────────────────────


def test_a_blank_form_holds_what_each_kind_starts_at():
    blank = bench_api.blank_values(bench_api.inputs_for(RampArgs))

    assert blank == {
        "element": Element.UPPER.value,
        "celsius": 0,
        "hold": False,
        "watching": 0,
        "seal": "",
        "steps": [],
    }


# ── A filled form ────────────────────────────────────────────────────────────


def test_values_arrive_as_the_python_each_kind_promises():
    taken = bench_api.coerced_values(
        bench_api.inputs_for(RampArgs),
        {
            "element": "1",
            "celsius": "200",
            "hold": True,
            "watching": "3",
            "seal": "0a ff",
        },
    )

    assert taken == {
        "element": 1,
        "celsius": 200,
        "hold": True,
        "watching": 3,
        "seal": b"\x0a\xff",
    }


def test_a_repeating_field_comes_back_as_rows_of_python():
    taken = bench_api.coerced_values(
        bench_api.inputs_for(RampArgs),
        {"steps": [{"celsius": "20", "minutes": "5"}]},
    )

    assert taken == {"steps": [{"celsius": 20, "minutes": 5}]}


def test_a_value_nobody_submitted_is_left_out_rather_than_guessed_at():
    assert bench_api.coerced_values(bench_api.inputs_for(RampArgs), {}) == {}


def test_hex_an_operator_typed_reads_as_the_bytes_it_stands_for():
    assert bench_api.as_bytes("0x0aff") == b"\x0a\xff"
    assert bench_api.as_bytes("a ff") == b"\x0a\xff"
    assert bench_api.as_bytes("") == b""


def test_something_that_is_not_hexadecimal_is_refused():
    with pytest.raises(ValueError, match="not hexadecimal"):
        bench_api.as_bytes("zz")


# ── Options that move ────────────────────────────────────────────────────────


def test_a_live_list_is_called_for_each_time_it_is_drawn():
    seen = []

    def ports():
        seen.append(1)
        return ("/dev/oven0",)

    item = bench_api.choice("port", ports)
    assert bench_api.labelled_options(item) == (
        {"value": "/dev/oven0", "label": "/dev/oven0"},
    )
    bench_api.labelled_options(item)
    assert len(seen) == 2


def test_an_enum_labels_itself_by_name_and_sends_its_value():
    assert bench_api.labelled_options(bench_api.choice("element", Element)) == (
        {"value": 0, "label": "UPPER"},
        {"value": 1, "label": "LOWER"},
    )


def test_a_flag_set_offers_one_option_per_member():
    assert [
        o["label"] for o in bench_api.labelled_options(bench_api.bitmask("w", Watched))
    ] == [
        "TEMPERATURE",
        "CURRENT",
    ]
