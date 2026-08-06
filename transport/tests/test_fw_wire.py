import pytest

from transport import fw_api, fw_wire

# ── Splitting a byte stream into frames ──────────────────────────────────────


def test_a_frame_is_what_lies_between_two_delimiters():
    splitter = fw_wire.FrameSplitter()
    assert splitter.feed(b"abc\x00") == [b"abc"]


def test_a_frame_split_across_reads_is_still_one_frame():
    splitter = fw_wire.FrameSplitter()
    assert splitter.feed(b"ab") == []
    assert splitter.feed(b"cd\x00") == [b"abcd"]


def test_empty_runs_are_not_frames():
    splitter = fw_wire.FrameSplitter()
    assert splitter.feed(b"\x00\x00ab\x00\x00cd\x00") == [b"ab", b"cd"]


def test_a_run_past_the_bound_is_dropped_and_the_next_one_survives():
    splitter = fw_wire.FrameSplitter()
    assert splitter.feed(b"x" * (fw_wire.MAX_ENCODED + 1)) == []
    assert splitter.dropped == 1
    assert splitter.feed(b"junk\x00ab\x00") == [b"ab"]


# ── The codec, which is the firmware's own ───────────────────────────────────


def test_a_request_survives_the_round_trip_through_the_wire_format():
    args = fw_api.rpc_raw_read_args(idx=1, reg=fw_api.TMC2209_CHOPCONF)
    stream = fw_wire.encode(
        fw_wire.seal_request(
            0x1234, fw_api.RPC_NS_RAW, fw_api.RPC_RAW_READ, bytes(args)
        )
    )

    runs = fw_wire.FrameSplitter().feed(stream)
    assert len(runs) == 1

    frame = fw_wire.open_frame(runs[0])
    assert frame is not None
    assert frame.type == fw_api.RPC_FRAME_REQ
    assert frame.header.id == 0x1234
    assert frame.header.ns == fw_api.RPC_NS_RAW
    assert frame.header.method == fw_api.RPC_RAW_READ

    back = fw_api.rpc_raw_read_args.from_buffer_copy(frame.payload)
    assert (back.idx, back.reg) == (1, fw_api.TMC2209_CHOPCONF)


def test_the_encoding_carries_no_delimiter_of_its_own():
    payload = bytes(fw_api.rpc_raw_read_args(idx=0, reg=0))
    frame = fw_wire.seal_request(0, fw_api.RPC_NS_RAW, fw_api.RPC_RAW_READ, payload)
    encoded = fw_wire.encode(frame)

    assert b"\x00" in frame
    assert encoded.endswith(b"\x00")
    assert b"\x00" not in encoded[:-1]


def test_a_corrupted_frame_does_not_open():
    frame = bytearray(
        fw_wire.seal_request(7, fw_api.RPC_NS_SYS, fw_api.RPC_SYS_STATE, b"")
    )
    frame[fw_api.RPC_HDR_LEN - 1] ^= 0xFF
    runs = fw_wire.FrameSplitter().feed(fw_wire.encode(bytes(frame)))
    assert fw_wire.open_frame(runs[0]) is None


def test_a_run_that_is_not_cobs_does_not_open():
    assert fw_wire.open_frame(b"\x05ab") is None


def test_a_payload_too_large_to_frame_is_refused():
    with pytest.raises(fw_wire.WireError):
        fw_wire.seal_request(
            0, fw_api.RPC_NS_SYS, 0, b"x" * (fw_api.RPC_MAX_PAYLOAD + 1)
        )
