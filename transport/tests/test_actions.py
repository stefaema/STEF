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

    bench_api.load("transport.bench")
    read = bench_api.REGISTRY.subsystem("transport").actions["raw.read"]
    idx = next(p for p in read.params if p.name == "idx")
    assert idx.kind is bench_api.Kind.CHOICE
    assert idx.catalog == "devices"


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


def test_a_reply_that_carries_nothing_still_says_the_call_was_made():
    assert actions.as_result("raw.halt", None).summary == "raw.halt returned"


def test_bytes_nobody_declared_as_characters_stay_hexadecimal():
    assert actions._render(b"\xde\xad") == "de ad"


def test_a_long_headline_is_clipped_rather_than_wrapped():
    line = actions._clipped("x" * (actions.SUMMARY + 40))
    assert len(line) == actions.SUMMARY
    assert line.endswith("...")
