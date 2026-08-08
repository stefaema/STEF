import ctypes
import dataclasses

import pytest

from shared import fw_api

# ── Payloads that end in a flexible array ────────────────────────────────────


def test_packing_sizes_the_flexible_member_and_sets_its_count():
    datagram = bytes(range(8))
    packed = fw_api.pack(
        fw_api.rpc_relay_send_args, {"idx": 0, "reply_len": 8, "tx": datagram}
    )

    assert len(packed) == ctypes.sizeof(fw_api.rpc_relay_send_args) + len(datagram)
    head = fw_api.rpc_relay_send_args.from_buffer_copy(
        packed[: ctypes.sizeof(fw_api.rpc_relay_send_args)]
    )
    assert head.count == len(datagram)
    assert packed[ctypes.sizeof(fw_api.rpc_relay_send_args) :] == datagram


def test_packing_a_batch_of_structs_counts_the_elements_not_the_bytes():
    ops = [fw_api.rpc_op_t(reg=fw_api.TMC2209_GCONF, value=0xC0)]
    packed = fw_api.pack(fw_api.rpc_raw_write_args, {"idx": 0, "ops": ops})

    head = fw_api.rpc_raw_write_args.from_buffer_copy(
        packed[: ctypes.sizeof(fw_api.rpc_raw_write_args)]
    )
    assert head.count == 1
    assert len(packed) == ctypes.sizeof(fw_api.rpc_raw_write_args) + ctypes.sizeof(
        fw_api.rpc_op_t
    )


def test_unpacking_recovers_the_elements_the_count_promises():
    head = fw_api.rpc_sys_devices_ret(count=2)
    devs = (fw_api.rpc_dev_info_t * 2)(
        fw_api.rpc_dev_info_t(name=b"capstan", addr=0, wired=15),
        fw_api.rpc_dev_info_t(name=b"tension", addr=1, wired=15),
    )

    out = fw_api.unpack(fw_api.rpc_sys_devices_ret, bytes(head) + bytes(devs))
    assert out.count == 2
    assert [d.name.decode() for d in out.devs] == ["capstan", "tension"]


def test_a_reply_truncated_at_its_tail_still_unpacks():
    ret = fw_api.rpc_relay_send_ret(outcome=fw_api.RPC_RX_TIMEOUT, count=0)
    short = bytes(ret)[: fw_api.rpc_relay_send_ret.rx.offset]
    assert len(short) < ctypes.sizeof(fw_api.rpc_relay_send_ret)

    out = fw_api.unpack(fw_api.rpc_relay_send_ret, short)
    assert out.outcome == fw_api.RPC_RX_TIMEOUT
    assert out.count == 0


def test_a_count_the_payload_does_not_back_is_refused():
    head = fw_api.rpc_sys_devices_ret(count=4)
    with pytest.raises(fw_api.ApiError):
        fw_api.unpack(fw_api.rpc_sys_devices_ret, bytes(head))


# ── The surface derived from the enums ───────────────────────────────────────


def test_the_namespaces_are_the_ones_with_methods():
    assert set(fw_api.namespaces()) == {"sys", "relay", "raw"}


def test_every_method_carries_at_least_one_payload():
    for specs in fw_api.namespaces().values():
        for spec in specs.values():
            assert spec.args is not None or spec.ret is not None, spec.name


def test_no_terminator_became_a_method():
    for specs in fw_api.namespaces().values():
        assert "count" not in specs


def test_a_method_finds_the_payloads_its_own_name_predicts():
    raw = fw_api.namespaces()["raw"]
    assert raw["poll_health"].wire == (
        fw_api.rpc_dev_args,
        fw_api.rpc_raw_poll_health_ret,
    )
    assert raw["poll_health"].args is fw_api.dataclass_for(fw_api.rpc_dev_args)
    assert raw["enable"].ret is None

    relay = fw_api.namespaces()["relay"]
    assert relay["send"].method == fw_api.RPC_RELAY_SEND
    assert relay["send"].fields == ("idx", "reply_len", "tx")

    sys_ns = fw_api.namespaces()["sys"]
    assert sys_ns["version"].args is None
    assert sys_ns["version"].wire[1] is fw_api.rpc_sys_version_ret


def test_binding_attaches_every_namespace_to_one_carrier():
    seen = []
    surface = fw_api.attach(lambda spec, args, kwargs: seen.append(spec.name))

    assert set(surface) == set(fw_api.namespaces())
    surface["raw"].poll_health(0)
    surface["sys"].version()
    assert seen == ["raw.poll_health", "sys.version"]


def test_the_abi_is_reachable_without_naming_it():
    assert fw_api.RPC_OK == 0
    assert fw_api.rpc_relay_send_args is not None
    assert fw_api.TMC2209_GCONF == 0
    assert "rpc_raw_move_args" in dir(fw_api)
    assert "attach" in dir(fw_api)


def test_a_name_neither_module_has_still_fails():
    with pytest.raises(AttributeError):
        fw_api.rpc_no_such_thing


# ── The payloads, as Python rather than as ctypes ────────────────────────────


def payload_records():
    """Return every record a method names, and every record nested inside one.

    Not all of SIZEOF: rpc_view_t and rpc_buf_t hold a frame host-side and one
    of them carries a pointer.
    """
    found = set()
    for specs in fw_api.namespaces().values():
        for spec in specs.values():
            found.update(record for record in spec.wire if record is not None)
    nested = {
        flex.elem
        for record, flex in fw_api.FLEX.items()
        if record in found and flex.elem.__name__ in fw_api.SIZEOF
    }
    return sorted(found | nested, key=lambda record: record.__name__)


PAYLOADS = payload_records()


@pytest.mark.parametrize("record", PAYLOADS, ids=lambda r: r.__name__)
def test_a_payload_round_trips_through_its_dataclass(record):
    built = fw_api.dataclass_for(record)()
    raw = fw_api.encode(record, built)
    assert fw_api.decode(record, raw) == built
    assert fw_api.encode(record, fw_api.decode(record, raw)) == raw


@pytest.mark.parametrize("record", PAYLOADS, ids=lambda r: r.__name__)
def test_the_bytes_are_the_ones_ctypes_produced_before(record):
    # The guard on the surface: a dataclass and a ctypes struct seal alike.
    if record in fw_api.FLEX:
        pytest.skip("a flexible member has no zero-length ctypes equivalent")
    assert fw_api.encode(record, fw_api.dataclass_for(record)()) == bytes(record())


@pytest.mark.parametrize("record", PAYLOADS, ids=lambda r: r.__name__)
def test_no_padding_survives_into_the_dataclass(record):
    names = {f.name for f in dataclasses.fields(fw_api.dataclass_for(record))}
    assert not [n for n in names if n.startswith("_pad")]
    flex = fw_api.FLEX.get(record)
    if flex is not None:
        assert flex.count_field not in names
        assert flex.field in names


def test_a_field_comes_back_as_the_kind_its_typedef_named():
    args = fw_api.namespaces()["raw"]["move"].args(
        idx=1, dir=fw_api.Tmc2209Level.HIGH, shaft=True, pulses=4000
    )
    back = fw_api.decode(
        fw_api.rpc_raw_move_args, fw_api.encode(fw_api.rpc_raw_move_args, args)
    )

    assert back.dir is fw_api.Tmc2209Level.TMC2209_HIGH
    assert back.shaft is True
    assert isinstance(back.pulses, int) and not isinstance(back.pulses, bool)


def test_a_mask_comes_back_as_the_flag_set_it_names():
    devices = fw_api.rpc_sys_devices_ret(count=1)
    one = fw_api.rpc_dev_info_t(name=b"capstan", addr=0, wired=0b0101, has_uart=1)

    out = fw_api.decode(fw_api.rpc_sys_devices_ret, bytes(devices) + bytes(one))
    (dev,) = out.devs

    assert isinstance(out.devs, list)
    assert dev.name == b"capstan"
    assert dev.has_uart is True
    assert dev.has_stepgen is False
    assert dev.wired is fw_api.Tmc2209LineMask.ENN | fw_api.Tmc2209LineMask.STEP


def test_a_conditions_mask_decodes_to_the_conditions_it_holds():
    raw = fw_api.rpc_raw_poll_health_ret(
        conditions=fw_api.TMC2209_STANDSTILL | fw_api.TMC2209_OPEN_LOAD
    )
    out = fw_api.decode(fw_api.rpc_raw_poll_health_ret, bytes(raw))

    assert out.conditions is (
        fw_api.Tmc2209Condition.STANDSTILL | fw_api.Tmc2209Condition.OPEN_LOAD
    )


def test_a_short_reply_still_unpacks_into_a_dataclass():
    ret = fw_api.rpc_relay_send_ret(outcome=fw_api.RPC_RX_TIMEOUT, count=0)
    short = bytes(ret)[: fw_api.rpc_relay_send_ret.rx.offset]

    out = fw_api.decode(fw_api.rpc_relay_send_ret, short)
    assert out.outcome == fw_api.RPC_RX_TIMEOUT
    # A fixed field with no terminator reads back whole. Trimming by count
    # belongs to whoever knows what count means, not to the codec.
    assert out.rx == bytes(fw_api.RPC_RELAY_MAX_BYTES)


def test_a_flexible_member_of_records_travels_as_a_list():
    ops = [
        fw_api.dataclass_for(fw_api.rpc_op_t)(reg=fw_api.Tmc2209Reg.GCONF, value=0xC1),
        fw_api.dataclass_for(fw_api.rpc_op_t)(reg=fw_api.Tmc2209Reg.CHOPCONF, value=9),
    ]
    args = fw_api.namespaces()["raw"]["write"].args(idx=0, ops=ops)

    raw = fw_api.encode(fw_api.rpc_raw_write_args, args)
    back = fw_api.decode(fw_api.rpc_raw_write_args, raw)

    assert len(raw) == ctypes.sizeof(fw_api.rpc_raw_write_args) + 2 * ctypes.sizeof(
        fw_api.rpc_op_t
    )
    assert back.ops == ops
    assert back.ops[0].reg is fw_api.Tmc2209Reg.TMC2209_GCONF


def test_arguments_a_caller_leaves_out_are_what_zeroed_bytes_would_decode_to():
    spec = fw_api.namespaces()["raw"]["move"]
    assert fw_api.arguments(spec, (1,), {}) == bytes(fw_api.rpc_raw_move_args(idx=1))


def test_a_reply_reaches_the_caller_as_a_dataclass():
    spec = fw_api.namespaces()["sys"]["state"]
    payload = bytes(
        fw_api.rpc_sys_state_ret(
            uptime_ms=1234, device_count=3, mode=fw_api.RPC_MODE_SCANNING, ready=1
        )
    )

    out = fw_api.result(spec, payload)
    assert out.mode is fw_api.RpcMode.SCANNING
    assert out.ready is True
    assert out.uptime_ms == 1234
