import ctypes

import pytest

from transport import fw_api

BOUND_FUNCTION = type(fw_api.rpc_strerror)

STATUSES = list(range(fw_api.RPC_STATUS_LAST)) + [
    fw_api.RPC_NO_METHOD,
    fw_api.RPC_BAD_FRAME,
    fw_api.RPC_INTERNAL,
]


@pytest.mark.parametrize("name", sorted(fw_api.SIZEOF))
def test_clang_and_gcc_agree_on_size(name):
    assert ctypes.sizeof(getattr(fw_api, name)) == fw_api.SIZEOF[name]


@pytest.mark.parametrize("status", STATUSES)
def test_every_status_names_itself(status):
    assert fw_api.rpc_strerror(status).decode() != "unknown"


@pytest.mark.parametrize("status", STATUSES)
def test_every_status_but_ok_has_an_exception(status):
    if status == fw_api.RPC_OK:
        assert status not in fw_api.STATUS_EXCEPTION
    else:
        assert issubclass(fw_api.STATUS_EXCEPTION[status], fw_api.RpcError)


def test_ok_does_not_raise():
    fw_api.raise_for_status(fw_api.RPC_OK)


def test_raising_carries_the_status_and_its_name():
    with pytest.raises(fw_api.RpcNoAck) as caught:
        fw_api.raise_for_status(fw_api.RPC_NO_ACK)
    assert caught.value.status == fw_api.RPC_NO_ACK
    assert "IFCNT" in str(caught.value)


def test_an_unnamed_status_still_raises():
    with pytest.raises(fw_api.RpcError):
        fw_api.raise_for_status(200)


def test_every_symbol_resolved_at_import():
    bound = [v for v in vars(fw_api).values() if isinstance(v, BOUND_FUNCTION)]
    assert bound
    assert all(f.argtypes is not None for f in bound)


def test_a_sealed_request_opens_as_what_went_in():
    buf = fw_api.rpc_buf_t()
    args = fw_api.rpc_raw_move_args(
        idx=1,
        dir=0,
        shaft=1,
        pulses=4000,
        pullin_pps=200,
        cruise_pps=8000,
        accel_pps_s=1000,
    )
    ctypes.memmove(
        ctypes.byref(buf, fw_api.RPC_HDR_LEN), ctypes.byref(args), ctypes.sizeof(args)
    )
    length = fw_api.rpc_frame_seal_req(
        buf, 7, fw_api.RPC_NS_RAW, fw_api.RPC_RAW_MOVE, ctypes.sizeof(args)
    )
    assert length == fw_api.RPC_HDR_LEN + ctypes.sizeof(args) + fw_api.RPC_CRC_LEN

    view = fw_api.rpc_view_t()
    assert fw_api.rpc_frame_open(ctypes.byref(buf), length, ctypes.byref(view))
    assert view.type == fw_api.RPC_FRAME_REQ
    assert view.payload_len == ctypes.sizeof(args)

    back = fw_api.rpc_raw_move_args.from_buffer_copy(
        ctypes.string_at(view.payload, view.payload_len)
    )
    assert (back.idx, back.shaft, back.pulses, back.cruise_pps) == (1, 1, 4000, 8000)


def test_a_corrupted_frame_does_not_open():
    buf = fw_api.rpc_buf_t()
    length = fw_api.rpc_frame_seal_rep(buf, 7, fw_api.RPC_OK, 0)
    buf.bytes[fw_api.RPC_HDR_LEN - 1] ^= 0xFF
    assert not fw_api.rpc_frame_open(
        ctypes.byref(buf), length, ctypes.byref(fw_api.rpc_view_t())
    )


def test_the_codec_is_the_firmwares_own():
    gconf = fw_api.tmc2209_gconf_t(
        en_spreadcycle=True, pdn_disable=True, mstep_reg_select=True
    )
    raw = fw_api.tmc2209_gconf_encode(ctypes.byref(gconf))
    back = fw_api.tmc2209_gconf_decode(raw)
    assert (back.en_spreadcycle, back.pdn_disable, back.mstep_reg_select) == (
        True,
        True,
        True,
    )
    assert not back.shaft


def test_a_datagram_this_process_built_parses_here_too():
    out = (ctypes.c_uint8 * fw_api.TMC2209_WRITE_LEN)()
    fw_api.tmc2209_frame_write(out, 0, fw_api.TMC2209_GCONF, 0x1234)

    reply = (ctypes.c_uint8 * fw_api.TMC2209_REPLY_LEN)(
        fw_api.TMC2209_SYNC, fw_api.TMC2209_MASTER_ADDR, fw_api.TMC2209_GCONF, *out[3:7]
    )
    reply[7] = fw_api.tmc2209_crc8(reply, fw_api.TMC2209_REPLY_LEN - 1)

    value = ctypes.c_uint32()
    err = fw_api.tmc2209_frame_parse_reply(
        reply, fw_api.TMC2209_GCONF, ctypes.byref(value)
    )
    assert err == fw_api.TMC2209_OK
    assert value.value == 0x1234


@pytest.mark.parametrize("head", list(fw_api.FLEX))
def test_a_flexible_member_is_named_but_not_laid_out(head):
    flex = fw_api.FLEX[head]
    laid_out = [name for name, _ in head._fields_]
    assert flex.field not in laid_out
    assert flex.count_field in laid_out


def test_the_register_table_is_the_librarys():
    classes = [
        fw_api.tmc2209_reg_class_at(slot) for slot in range(fw_api.TMC2209_REG_COUNT)
    ]
    assert classes.count(fw_api.TMC2209_CLASS_OWNED) == fw_api.TMC2209_OWNED_COUNT
    assert fw_api.TMC2209_CLASS_UNKNOWN not in classes
    assert fw_api.tmc2209_reg_name(fw_api.TMC2209_CHOPCONF).decode() == "CHOPCONF"
