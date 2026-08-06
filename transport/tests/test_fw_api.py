import ctypes

import pytest

from transport import fw_api

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
    assert raw["poll_health"].args is fw_api.rpc_dev_args
    assert raw["poll_health"].ret is fw_api.rpc_raw_poll_health_ret
    assert raw["enable"].ret is None

    relay = fw_api.namespaces()["relay"]
    assert relay["send"].method == fw_api.RPC_RELAY_SEND
    assert relay["send"].fields == ("idx", "reply_len", "tx")

    sys_ns = fw_api.namespaces()["sys"]
    assert sys_ns["version"].args is None
    assert sys_ns["version"].ret is fw_api.rpc_sys_version_ret


def test_binding_attaches_every_namespace_to_one_carrier():
    seen = []
    surface = fw_api.bind(lambda spec, args, kwargs: seen.append(spec.name))

    assert set(surface) == set(fw_api.namespaces())
    surface["raw"].poll_health(0)
    surface["sys"].version()
    assert seen == ["raw.poll_health", "sys.version"]


def test_the_abi_is_reachable_without_naming_it():
    assert fw_api.RPC_OK == 0
    assert fw_api.rpc_relay_send_args is not None
    assert fw_api.TMC2209_GCONF == 0
    assert "rpc_raw_move_args" in dir(fw_api)
    assert "bind" in dir(fw_api)


def test_a_name_neither_module_has_still_fails():
    with pytest.raises(AttributeError):
        fw_api.rpc_no_such_thing
