"""Every row of the derivation table, including the row that is an error."""

from dataclasses import dataclass

import pytest

from shared import bench_api
from shared.bench_api import DerivationError, Kind, integer, params_for, with_declared
from shared.bench_api.tests.fixture.payloads import (
    ClearArgs,
    Condition,
    MoveArgs,
    Op,
    ReadArgs,
    Register,
    SendArgs,
    Unrenderable,
    WriteArgs,
)


def kinds(target):
    """Return each derived parameter as a name and kind pair."""
    return [(p.name, p.kind) for p in params_for(target)]


def test_a_bool_becomes_an_on_or_off_control():
    assert ("forward", Kind.BOOLEAN) in kinds(MoveArgs)


def test_an_int_becomes_a_number_control_with_no_bounds_of_its_own():
    (pulses,) = [p for p in params_for(MoveArgs) if p.name == "pulses"]
    assert pulses.kind is Kind.INTEGER
    # An annotation cannot say whether this is a 0..31 current setting or a step
    # count, so bounds stay the residue @action declares.
    assert (pulses.min, pulses.max, pulses.unit) == (None, None, None)


def test_an_int_enum_becomes_a_pick_one_over_its_members():
    (reg,) = [p for p in params_for(ReadArgs) if p.name == "reg"]
    assert reg.kind is Kind.CHOICE
    assert list(reg.resolved()) == list(Register)
    assert reg.catalog is None


def test_an_int_flag_becomes_a_pick_many_over_its_members():
    (conditions,) = [p for p in params_for(ClearArgs) if p.name == "conditions"]
    assert conditions.kind is Kind.BITMASK
    assert list(conditions.resolved()) == list(Condition)


def test_bytes_become_a_control_the_caller_assembles():
    assert ("tx", Kind.RAW_BYTES) in kinds(SendArgs)


def test_a_list_of_dataclasses_becomes_a_group_whose_columns_derive_too():
    (ops,) = [p for p in params_for(WriteArgs) if p.name == "ops"]
    assert ops.kind is Kind.GROUP
    assert [(c.name, c.kind) for c in ops.columns] == [
        ("reg", Kind.CHOICE),
        ("value", Kind.INTEGER),
    ]
    assert list(ops.columns[0].resolved()) == list(Register)


def test_parameters_keep_the_order_the_fields_were_declared_in():
    assert [name for name, _ in kinds(MoveArgs)] == [
        "idx",
        "forward",
        "pulses",
        "cruise_pps",
    ]


def test_a_type_no_kind_renders_is_an_error_that_names_the_field():
    with pytest.raises(DerivationError) as caught:
        params_for(Unrenderable)
    assert "Unrenderable.when" in str(caught.value)


def test_a_list_of_something_that_is_not_a_dataclass_is_refused():
    @dataclass
    class Loose:
        rows: list[int]

    with pytest.raises(DerivationError):
        params_for(Loose)


def test_something_that_is_not_a_dataclass_at_all_is_refused():
    with pytest.raises(DerivationError):
        params_for(int)


def test_a_string_annotation_resolves_the_same_way():
    # `from __future__ import annotations` makes every annotation a string, so
    # get_type_hints rather than raw __annotations__ is what has to be read.
    assert kinds(Op) == [("reg", Kind.CHOICE), ("value", Kind.INTEGER)]


# ── The residue a declaration adds ───────────────────────────────────────────


def test_a_declared_entry_replaces_one_field_and_leaves_the_rest_derived():
    derived = params_for(MoveArgs)
    merged = with_declared(derived, (integer("cruise_pps", unit="pps", max=3200),))

    assert [p.name for p in merged] == [p.name for p in derived]
    (cruise,) = [p for p in merged if p.name == "cruise_pps"]
    assert (cruise.unit, cruise.max) == ("pps", 3200)
    assert [p for p in merged if p.name != "cruise_pps"] == [
        p for p in derived if p.name != "cruise_pps"
    ]


def test_a_declared_entry_naming_no_such_field_is_refused():
    with pytest.raises(DerivationError) as caught:
        with_declared(params_for(MoveArgs), (integer("cruise_rpm"),))
    assert "cruise_rpm" in str(caught.value)


def test_a_live_option_list_is_fetched_by_the_functions_own_name():
    seen = []

    def serial_ports():
        """Return what is plugged in right now."""
        seen.append(1)
        return ("auto", "/dev/ttyACM0")

    port = bench_api.choice("port", serial_ports)
    assert port.catalog == "serial_ports"
    assert port.live
    assert list(port.resolved()) == ["auto", "/dev/ttyACM0"]
    assert list(port.resolved()) == ["auto", "/dev/ttyACM0"]
    assert len(seen) == 2


def test_two_parameters_passing_one_callable_share_one_list():
    def devices():
        """Return the board table."""
        return ("capstan",)

    assert bench_api.choice("idx", devices).catalog == (
        bench_api.choice("other", devices).catalog
    )


def test_a_fixed_list_ships_inline_and_is_not_fetched():
    port = bench_api.choice("port", ("auto", "manual"))
    assert not port.live
    assert port.catalog is None
