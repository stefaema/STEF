import pytest

from shared import subsystem
from shared.subsystem import Input
from shared.subsystem.tests.fixture.payloads import Element, RampArgs, Watched

# ── The inputs an annotated payload implies ──────────────────────────────────


def kinds_of(payload):
    """Return each derived input as name and kind."""
    return {item.name: item.kind for item in subsystem.inputs_for(payload)}


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
    steps = next(i for i in subsystem.inputs_for(RampArgs) if i.name == "steps")

    assert [column.name for column in steps.columns] == ["celsius", "minutes"]


def test_the_prose_beside_a_field_becomes_the_control_s_hint():
    celsius = next(i for i in subsystem.inputs_for(RampArgs) if i.name == "celsius")

    assert celsius.hint == "where it settles"


def test_a_type_nobody_decided_how_to_draw_is_refused_by_field_name():
    from dataclasses import dataclass

    @dataclass
    class Odd:
        when: complex

    with pytest.raises(subsystem.DeclarationError, match="Odd.when"):
        subsystem.inputs_for(Odd)


def test_taking_no_payload_derives_no_form():
    assert subsystem.inputs_for(None) == ()


def test_an_override_replaces_one_field_and_leaves_the_rest_derived():
    derived = subsystem.inputs_for(RampArgs)
    mine = subsystem.choice("element", (0, 1))

    settled = subsystem.overridden(derived, {"element": mine})

    assert settled[0] is mine
    assert [item.name for item in settled] == [item.name for item in derived]


def test_an_override_naming_no_field_is_refused():
    with pytest.raises(subsystem.DeclarationError, match="name no such field"):
        subsystem.overridden(
            subsystem.inputs_for(RampArgs), {"kelvin": subsystem.integer("kelvin")}
        )


# ── What a declaration refuses ───────────────────────────────────────────────


def test_a_kind_no_control_renders_is_refused():
    with pytest.raises(subsystem.DeclarationError, match="which no control renders"):
        subsystem.checked_inputs([Input(name="celsius", kind="dial")])


def test_a_pick_one_with_nothing_to_pick_from_is_refused():
    with pytest.raises(subsystem.DeclarationError, match="needs options"):
        subsystem.checked_inputs([Input(name="element", kind="choice")])


def test_a_group_with_no_columns_is_refused():
    with pytest.raises(subsystem.DeclarationError, match="needs columns"):
        subsystem.checked_inputs([Input(name="steps", kind="group")])


def test_a_column_is_checked_the_way_a_control_is():
    with pytest.raises(subsystem.DeclarationError, match="which no control renders"):
        subsystem.checked_inputs(
            [subsystem.group("steps", columns=[Input(name="celsius", kind="dial")])]
        )


# ── What a blank form holds ──────────────────────────────────────────────────


def test_a_blank_form_holds_what_each_kind_starts_at():
    blank = subsystem.blank_values(subsystem.inputs_for(RampArgs))

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
    taken = subsystem.coerced_values(
        subsystem.inputs_for(RampArgs),
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
    taken = subsystem.coerced_values(
        subsystem.inputs_for(RampArgs),
        {"steps": [{"celsius": "20", "minutes": "5"}]},
    )

    assert taken == {"steps": [{"celsius": 20, "minutes": 5}]}


def test_a_value_nobody_submitted_is_left_out_rather_than_guessed_at():
    assert subsystem.coerced_values(subsystem.inputs_for(RampArgs), {}) == {}


def test_hex_an_operator_typed_reads_as_the_bytes_it_stands_for():
    assert subsystem.as_bytes("0x0aff") == b"\x0a\xff"
    assert subsystem.as_bytes("a ff") == b"\x0a\xff"
    assert subsystem.as_bytes("") == b""


def test_something_that_is_not_hexadecimal_is_refused():
    with pytest.raises(ValueError, match="not hexadecimal"):
        subsystem.as_bytes("zz")


# ── Options that move ────────────────────────────────────────────────────────


def test_a_live_list_is_called_for_each_time_it_is_drawn():
    seen = []

    def ports(sub):
        seen.append(1)
        return ("/dev/oven0",)

    item = subsystem.choice("port", ports)
    assert subsystem.labelled_options(item, object()) == (
        {"value": "/dev/oven0", "label": "/dev/oven0"},
    )
    subsystem.labelled_options(item)
    assert len(seen) == 2


def test_an_enum_labels_itself_by_name_and_sends_its_value():
    assert subsystem.labelled_options(subsystem.choice("element", Element)) == (
        {"value": 0, "label": "UPPER"},
        {"value": 1, "label": "LOWER"},
    )


def test_a_flag_set_offers_one_option_per_member():
    assert [
        o["label"] for o in subsystem.labelled_options(subsystem.bitmask("w", Watched))
    ] == [
        "TEMPERATURE",
        "CURRENT",
    ]


def test_a_live_list_is_asked_of_the_subsystem_it_belongs_to():
    oven = object()
    item = subsystem.choice("port", lambda sub: ("upper",) if sub is oven else ())

    assert subsystem.labelled_options(item, oven) == (
        {"value": "upper", "label": "upper"},
    )


@pytest.mark.parametrize("sent", ["false", "0", "off", "", False])
def test_a_boolean_sent_as_false_text_is_false(sent):
    assert subsystem.coerced(subsystem.boolean("hold"), sent) is False


def test_a_confirmation_offers_only_continue():
    asked = subsystem.confirmation("Thread the film.")

    assert asked.hint == "Thread the film."
    assert subsystem.labelled_options(asked) == ({"value": True, "label": "Continue"},)
    assert subsystem.coerced(asked, "True") is True


def test_a_choice_sent_as_text_comes_back_as_the_option_it_names():
    item = subsystem.choice("iso", lambda sub: ("400", "800"))

    assert subsystem.coerced(item, "800", object()) == "800"


def test_a_choice_of_numbers_sent_as_text_comes_back_as_a_number():
    assert subsystem.coerced(subsystem.choice("element", Element), "1") == 1
