"""A form's controls, and the values that come back through them."""

import pytest

from shared.bench_api import Option, ParamError, arguments, choice, raw_bytes
from shared.bench_api.params import initial, labelled

# ── What an operator reads against what the call takes ───────────────────────


def test_an_option_may_read_differently_from_what_the_call_takes():
    assert labelled(Option("/dev/ttyACM0", "/dev/ttyACM0 (a board)")) == {
        "value": "/dev/ttyACM0",
        "label": "/dev/ttyACM0 (a board)",
    }
    assert labelled("auto") == {"value": "auto", "label": "auto"}


def test_a_pick_starts_on_its_first_option():
    assert initial(choice("port", ("auto", "/dev/ttyACM0"))) == "auto"


def test_a_pick_with_nothing_to_pick_starts_empty():
    assert initial(choice("port", ())) is None


# ── Coercion, since a form arrives with a thinner vocabulary ─────────────────


def test_hex_typed_into_a_raw_field_becomes_bytes():
    field = raw_bytes("tx")
    assert arguments((field,), {"tx": "de ad be ef"}) == {"tx": b"\xde\xad\xbe\xef"}
    assert arguments((field,), {"tx": "0xdeadbeef"}) == {"tx": b"\xde\xad\xbe\xef"}
    assert arguments((field,), {"tx": ""}) == {"tx": b""}


def test_an_odd_number_of_hex_digits_is_read_as_a_leading_zero():
    assert arguments((raw_bytes("tx"),), {"tx": "f0f"}) == {"tx": b"\x0f\x0f"}


def test_something_that_is_not_hex_is_refused_rather_than_sent():
    with pytest.raises(ValueError, match="hexadecimal"):
        arguments((raw_bytes("tx"),), {"tx": "zz"})


def test_a_parameter_nobody_filled_in_is_left_out():
    assert arguments((raw_bytes("tx"),), {}) == {}


def test_a_bare_pair_is_refused_rather_than_labelled_as_itself():
    # A live list is only ever seen with hardware attached, so a pair left over
    # from before `Option` would otherwise reach the browser as its own repr.
    with pytest.raises(ParamError, match="Option"):
        labelled((0, "x_axis"))
