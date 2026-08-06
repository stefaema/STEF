import ctypes

import pytest

from shared.fw_api import abi

BOUND_FUNCTION = type(abi.rpc_strerror)

STATUSES = list(range(abi.RPC_STATUS_LAST)) + [
    abi.RPC_NO_METHOD,
    abi.RPC_BAD_FRAME,
    abi.RPC_INTERNAL,
]


@pytest.mark.parametrize("name", sorted(abi.SIZEOF))
def test_clang_and_gcc_agree_on_size(name):
    assert ctypes.sizeof(getattr(abi, name)) == abi.SIZEOF[name]


@pytest.mark.parametrize("status", STATUSES)
def test_every_status_names_itself(status):
    assert abi.rpc_strerror(status).decode() != "unknown"


@pytest.mark.parametrize("status", STATUSES)
def test_every_status_but_ok_has_an_exception(status):
    if status == abi.RPC_OK:
        assert status not in abi.STATUS_EXCEPTION
    else:
        assert issubclass(abi.STATUS_EXCEPTION[status], abi.RpcError)


def test_ok_does_not_raise():
    abi.raise_for_status(abi.RPC_OK)


def test_raising_carries_the_status_and_its_name():
    with pytest.raises(abi.RpcNoAck) as caught:
        abi.raise_for_status(abi.RPC_NO_ACK)
    assert caught.value.status == abi.RPC_NO_ACK
    assert "IFCNT" in str(caught.value)


def test_an_unnamed_status_still_raises():
    with pytest.raises(abi.RpcError):
        abi.raise_for_status(200)


def test_every_symbol_resolved_at_import():
    bound = [v for v in vars(abi).values() if isinstance(v, BOUND_FUNCTION)]
    assert bound
    assert all(f.argtypes is not None for f in bound)


def test_a_sealed_request_opens_as_what_went_in():
    buf = abi.rpc_buf_t()
    args = abi.rpc_raw_move_args(
        idx=1,
        dir=0,
        shaft=1,
        pulses=4000,
        pullin_pps=200,
        cruise_pps=8000,
        accel_pps_s=1000,
    )
    ctypes.memmove(
        ctypes.byref(buf, abi.RPC_HDR_LEN), ctypes.byref(args), ctypes.sizeof(args)
    )
    length = abi.rpc_frame_seal_req(
        buf, 7, abi.RPC_NS_RAW, abi.RPC_RAW_MOVE, ctypes.sizeof(args)
    )
    assert length == abi.RPC_HDR_LEN + ctypes.sizeof(args) + abi.RPC_CRC_LEN

    view = abi.rpc_view_t()
    assert abi.rpc_frame_open(ctypes.byref(buf), length, ctypes.byref(view))
    assert view.type == abi.RPC_FRAME_REQ
    assert view.payload_len == ctypes.sizeof(args)

    back = abi.rpc_raw_move_args.from_buffer_copy(
        ctypes.string_at(view.payload, view.payload_len)
    )
    assert (back.idx, back.shaft, back.pulses, back.cruise_pps) == (1, 1, 4000, 8000)


def test_a_corrupted_frame_does_not_open():
    buf = abi.rpc_buf_t()
    length = abi.rpc_frame_seal_rep(buf, 7, abi.RPC_OK, 0)
    buf.bytes[abi.RPC_HDR_LEN - 1] ^= 0xFF
    assert not abi.rpc_frame_open(
        ctypes.byref(buf), length, ctypes.byref(abi.rpc_view_t())
    )


def test_the_codec_is_the_firmwares_own():
    gconf = abi.tmc2209_gconf_t(
        en_spreadcycle=True, pdn_disable=True, mstep_reg_select=True
    )
    raw = abi.tmc2209_gconf_encode(ctypes.byref(gconf))
    back = abi.tmc2209_gconf_decode(raw)
    assert (back.en_spreadcycle, back.pdn_disable, back.mstep_reg_select) == (
        True,
        True,
        True,
    )
    assert not back.shaft


def test_a_datagram_this_process_built_parses_here_too():
    out = (ctypes.c_uint8 * abi.TMC2209_WRITE_LEN)()
    abi.tmc2209_frame_write(out, 0, abi.TMC2209_GCONF, 0x1234)

    reply = (ctypes.c_uint8 * abi.TMC2209_REPLY_LEN)(
        abi.TMC2209_SYNC, abi.TMC2209_MASTER_ADDR, abi.TMC2209_GCONF, *out[3:7]
    )
    reply[7] = abi.tmc2209_crc8(reply, abi.TMC2209_REPLY_LEN - 1)

    value = ctypes.c_uint32()
    err = abi.tmc2209_frame_parse_reply(reply, abi.TMC2209_GCONF, ctypes.byref(value))
    assert err == abi.TMC2209_OK
    assert value.value == 0x1234


@pytest.mark.parametrize("head", list(abi.FLEX))
def test_a_flexible_member_is_named_but_not_laid_out(head):
    flex = abi.FLEX[head]
    laid_out = [name for name, _ in head._fields_]
    assert flex.field not in laid_out
    assert flex.count_field in laid_out


def test_the_register_table_is_the_librarys():
    classes = [abi.tmc2209_reg_class_at(slot) for slot in range(abi.TMC2209_REG_COUNT)]
    assert classes.count(abi.TMC2209_CLASS_OWNED) == abi.TMC2209_OWNED_COUNT
    assert abi.TMC2209_CLASS_UNKNOWN not in classes
    assert abi.tmc2209_reg_name(abi.TMC2209_CHOPCONF).decode() == "CHOPCONF"
