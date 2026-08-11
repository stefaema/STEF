"""How a generated reply reads once it reaches a panel."""

import pytest

from shared import fw_api
from transport.bench import actions


@pytest.fixture(scope="module")
def sys_specs():
    """Return the sys namespace's method specs."""
    return fw_api.namespaces()["sys"]


def element_of(spec):
    """Return the dataclass one reply's repeating member holds."""
    return fw_api.dataclass_for(fw_api.FLEX[spec.wire[1]].elem)


def answer(spec, **values):
    """Return what one method's reply maps to, without a board to send it."""
    return actions.as_result(spec.name, spec.ret(**values), spec.wire[1])


def test_a_fixed_width_character_field_reads_as_the_name_it_holds(sys_specs):
    reply = answer(
        sys_specs["version"],
        protocol=1,
        reset_reason=11,
        project=b"stef_firmware",
        version=b"49100be-dirty",
        idf=b"v5.5.2",
    )
    assert dict(reply.fields)["project"] == "stef_firmware"
    assert dict(reply.fields)["version"] == "49100be-dirty"


def test_a_headline_carries_the_values_and_not_how_many_there_were(sys_specs):
    reply = answer(
        sys_specs["version"],
        protocol=1,
        reset_reason=11,
        project=b"stef_firmware",
        version=b"49100be-dirty",
        idf=b"v5.5.2",
    )
    assert "fields" not in reply.summary
    assert "project=stef_firmware" in reply.summary


def test_an_enum_reads_as_its_name_rather_than_its_number(sys_specs):
    reply = answer(
        sys_specs["state"],
        uptime_ms=225421,
        device_count=1,
        mode=fw_api.RpcMode(0),
        ready=True,
    )
    assert dict(reply.fields)["mode"].startswith("RPC_MODE")
    assert dict(reply.fields)["ready"] == "true"


def test_a_repeating_member_becomes_a_table_and_not_a_count(sys_specs):
    spec = sys_specs["devices"]
    element = element_of(spec)
    reply = actions.as_result(
        spec.name,
        spec.ret(
            devs=[element(name=b"capstan", addr=0), element(name=b"supply", addr=1)]
        ),
        spec.wire[1],
    )
    assert reply.table is not None
    assert "name" in reply.table.head
    assert len(reply.table.rows) == 2


def test_a_character_field_inside_a_repeating_member_reads_as_text_too(sys_specs):
    spec = sys_specs["devices"]
    element = element_of(spec)
    reply = actions.as_result(
        spec.name, spec.ret(devs=[element(name=b"capstan")]), spec.wire[1]
    )
    assert reply.table is not None
    named = reply.table.head.index("name")
    assert reply.table.rows[0][named] == "capstan"


def test_a_driver_is_chosen_by_name_and_never_by_a_bare_number():
    from shared import bench_api
    from shared.bench_api.params import options_name

    bench_api.load("transport.bench")
    read = bench_api.REGISTRY.subsystem("transport").actions["raw.read"]
    idx = next(p for p in read.params if p["name"] == "idx")
    assert idx["kind"] == "choice"
    assert options_name(idx) == "devices"


def test_the_driver_list_is_empty_rather_than_wrong_while_nothing_is_connected():
    assert actions.devices() == ()


def test_a_register_reply_is_shown_as_the_bits_it_stands_for():
    spec = fw_api.namespaces()["raw"]["poll_pins"]
    reply = actions.as_result(spec.name, spec.ret(value=0x210000C1), spec.wire[1])
    named = dict(reply.fields)
    assert named["enn"] == "true"
    assert named["ms1"] == "false"
    assert "version" in named
    assert "0x210000c1" in (reply.note or "")


def test_a_register_nobody_declared_a_codec_for_stays_a_number():
    spec = fw_api.namespaces()["raw"]["read"]
    reply = actions.as_result(spec.name, spec.ret(value=0x2A), spec.wire[1])
    assert dict(reply.fields) == {"value": "42 (0x2a)"}


# ── The register a reply carries ─────────────────────────────────────────────


def read_of(register, raw):
    """Return what `raw.read` maps to for one register, without a board to ask."""
    spec = fw_api.namespaces()["raw"]["read"]
    return actions.as_result(
        spec.name,
        spec.ret(value=raw),
        spec.wire[1],
        actions.asked_register(spec.name, spec.args(idx=0, reg=register)),
    )


def test_a_read_is_decoded_by_the_register_it_was_asked_for():
    # Which codec applies is an argument here, not a property of the method, so
    # it is the call's own arguments that pick it.
    reply = read_of(fw_api.TMC2209_GCONF, 0x000000C1)
    named = dict(reply.fields)
    assert named["i_scale_analog"] == "true"
    assert named["shaft"] == "false"
    assert "GCONF 0x000000c1" in (reply.note or "")


def test_two_registers_read_by_one_method_decode_differently():
    gconf = dict(read_of(fw_api.TMC2209_GCONF, 0x000000C1).fields)
    status = dict(read_of(fw_api.TMC2209_DRV_STATUS, 0xC0010000).fields)
    assert "i_scale_analog" in gconf and "i_scale_analog" not in status
    assert status["stst"] == "true"
    assert status["cs_actual"] == "1"


def test_a_codec_answering_one_number_gives_the_number_its_width_and_sign():
    # VACTUAL is 24-bit signed. The raw word does not carry that, so undecoded
    # this reads as 16777200 rather than as a reverse at 16 steps.
    assert dict(read_of(fw_api.TMC2209_VACTUAL, 0x00FFFFF0).fields) == {
        "VACTUAL": "-16"
    }


def test_a_scalar_register_keeps_its_number_and_takes_the_registers_name():
    assert dict(read_of(fw_api.TMC2209_TSTEP, 0x2A).fields) == {"TSTEP": "42 (0x2a)"}


def test_a_method_that_names_its_own_register_decodes_with_no_arguments_to_read():
    spec = fw_api.namespaces()["raw"]["poll_pins"]
    assert actions.asked_register(spec.name, None) is None
    reply = actions.as_result(spec.name, spec.ret(value=0x210000C1), spec.wire[1])
    assert dict(reply.fields)["enn"] == "true"


def test_a_register_outside_the_table_is_left_as_the_number_it_came_as():
    assert dict(read_of(0xFE, 0x2A).fields) == {"value": "42 (0x2a)"}


def test_a_reply_that_carries_nothing_still_says_the_call_was_made():
    assert actions.as_result("raw.halt", None).summary == "raw.halt returned"


def test_bytes_nobody_declared_as_characters_stay_hexadecimal():
    assert actions._render(b"\xde\xad") == "de ad"


def test_a_long_headline_is_clipped_rather_than_wrapped():
    line = actions._clipped("x" * (actions.SUMMARY + 40))
    assert len(line) == actions.SUMMARY
    assert line.endswith("...")
