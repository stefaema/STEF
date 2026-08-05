import ctypes
import threading
import time

import pytest

from transport import fw_abi, fw_link

TIMEOUT = 0.5


def seal_reply(request_id, status, payload=b""):
    buf = fw_abi.rpc_buf_t()
    if payload:
        ctypes.memmove(ctypes.byref(buf, fw_abi.RPC_HDR_LEN), payload, len(payload))
    length = fw_abi.rpc_frame_seal_rep(buf, request_id, status, len(payload))
    return fw_link.encode(bytes(buf.bytes[:length]))


def seal_log(level, uptime_ms, text):
    buf = fw_abi.rpc_buf_t()
    payload = text.encode()
    ctypes.memmove(ctypes.byref(buf, fw_abi.RPC_HDR_LEN), payload, len(payload))
    length = fw_abi.rpc_frame_seal_log(buf, level, uptime_ms, len(payload))
    return fw_link.encode(bytes(buf.bytes[:length]))


class FakeFirmware:
    def __init__(self, answer=None):
        self.answer = answer
        self.requests = []
        self.closed = False
        self._out = bytearray()
        self._splitter = fw_link.FrameSplitter()
        self._cv = threading.Condition()

    def push(self, data):
        with self._cv:
            self._out += data
            self._cv.notify_all()

    def write(self, data):
        for run in self._splitter.feed(data):
            frame = fw_link.open_frame(run)
            assert frame is not None
            self.requests.append(frame)
            if self.answer is not None:
                for reply in self.answer(self, frame):
                    self.push(reply)
        return len(data)

    def read(self, size):
        with self._cv:
            if not self._out:
                self._cv.wait(0.02)
            data = bytes(self._out[:size])
            del self._out[:size]
            return data

    @property
    def in_waiting(self):
        with self._cv:
            return len(self._out)

    def close(self):
        self.closed = True
        with self._cv:
            self._cv.notify_all()


def echo_state(_firmware, frame):
    ret = fw_abi.rpc_sys_state_ret(
        uptime_ms=1234, device_count=3, mode=fw_abi.RPC_MODE_IDLE, ready=1
    )
    return [seal_reply(frame.header.id, fw_abi.RPC_OK, bytes(ret))]


def linked(answer=None, **kwargs):
    firmware = FakeFirmware(answer)
    link = fw_link.FirmwareLink(stream=firmware, timeout=TIMEOUT, **kwargs)
    return firmware, link


def wait_until(predicate, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


# ── Splitting a byte stream into frames ──────────────────────────────────────


def test_a_frame_is_what_lies_between_two_delimiters():
    splitter = fw_link.FrameSplitter()
    assert splitter.feed(b"abc\x00") == [b"abc"]


def test_a_frame_split_across_reads_is_still_one_frame():
    splitter = fw_link.FrameSplitter()
    assert splitter.feed(b"ab") == []
    assert splitter.feed(b"cd\x00") == [b"abcd"]


def test_empty_runs_are_not_frames():
    splitter = fw_link.FrameSplitter()
    assert splitter.feed(b"\x00\x00ab\x00\x00cd\x00") == [b"ab", b"cd"]


def test_a_run_past_the_bound_is_dropped_and_the_next_one_survives():
    splitter = fw_link.FrameSplitter()
    assert splitter.feed(b"x" * (fw_link.MAX_ENCODED + 1)) == []
    assert splitter.dropped == 1
    assert splitter.feed(b"junk\x00ab\x00") == [b"ab"]


# ── The codec, which is the firmware's own ───────────────────────────────────


def test_a_request_survives_the_round_trip_through_the_wire_format():
    args = fw_abi.rpc_raw_read_args(idx=1, reg=fw_abi.TMC2209_CHOPCONF)
    stream = fw_link.encode(
        fw_link.seal_request(
            0x1234, fw_abi.RPC_NS_RAW, fw_abi.RPC_RAW_READ, bytes(args)
        )
    )

    runs = fw_link.FrameSplitter().feed(stream)
    assert len(runs) == 1

    frame = fw_link.open_frame(runs[0])
    assert frame is not None
    assert frame.type == fw_abi.RPC_FRAME_REQ
    assert frame.header.id == 0x1234
    assert frame.header.ns == fw_abi.RPC_NS_RAW
    assert frame.header.method == fw_abi.RPC_RAW_READ

    back = fw_abi.rpc_raw_read_args.from_buffer_copy(frame.payload)
    assert (back.idx, back.reg) == (1, fw_abi.TMC2209_CHOPCONF)


def test_the_encoding_carries_no_delimiter_of_its_own():
    payload = bytes(fw_abi.rpc_raw_read_args(idx=0, reg=0))
    frame = fw_link.seal_request(0, fw_abi.RPC_NS_RAW, fw_abi.RPC_RAW_READ, payload)
    encoded = fw_link.encode(frame)

    assert b"\x00" in frame
    assert encoded.endswith(b"\x00")
    assert b"\x00" not in encoded[:-1]


def test_a_corrupted_frame_does_not_open():
    frame = bytearray(
        fw_link.seal_request(7, fw_abi.RPC_NS_SYS, fw_abi.RPC_SYS_STATE, b"")
    )
    frame[fw_abi.RPC_HDR_LEN - 1] ^= 0xFF
    runs = fw_link.FrameSplitter().feed(fw_link.encode(bytes(frame)))
    assert fw_link.open_frame(runs[0]) is None


def test_a_run_that_is_not_cobs_does_not_open():
    assert fw_link.open_frame(b"\x05ab") is None


def test_a_payload_too_large_to_frame_is_refused():
    with pytest.raises(fw_link.LinkError):
        fw_link.seal_request(
            0, fw_abi.RPC_NS_SYS, 0, b"x" * (fw_abi.RPC_MAX_PAYLOAD + 1)
        )


# ── Payloads that end in a flexible array ────────────────────────────────────


def test_packing_sizes_the_flexible_member_and_sets_its_count():
    datagram = bytes(range(8))
    packed = fw_link.pack(
        fw_abi.rpc_relay_send_args, {"idx": 0, "reply_len": 8, "tx": datagram}
    )

    assert len(packed) == ctypes.sizeof(fw_abi.rpc_relay_send_args) + len(datagram)
    head = fw_abi.rpc_relay_send_args.from_buffer_copy(
        packed[: ctypes.sizeof(fw_abi.rpc_relay_send_args)]
    )
    assert head.count == len(datagram)
    assert packed[ctypes.sizeof(fw_abi.rpc_relay_send_args) :] == datagram


def test_packing_a_batch_of_structs_counts_the_elements_not_the_bytes():
    ops = [fw_abi.rpc_op_t(reg=fw_abi.TMC2209_GCONF, value=0xC0)]
    packed = fw_link.pack(fw_abi.rpc_raw_write_args, {"idx": 0, "ops": ops})

    head = fw_abi.rpc_raw_write_args.from_buffer_copy(
        packed[: ctypes.sizeof(fw_abi.rpc_raw_write_args)]
    )
    assert head.count == 1
    assert len(packed) == ctypes.sizeof(fw_abi.rpc_raw_write_args) + ctypes.sizeof(
        fw_abi.rpc_op_t
    )


def test_unpacking_recovers_the_elements_the_count_promises():
    head = fw_abi.rpc_sys_devices_ret(count=2)
    devs = (fw_abi.rpc_dev_info_t * 2)(
        fw_abi.rpc_dev_info_t(name=b"capstan", addr=0, wired=15),
        fw_abi.rpc_dev_info_t(name=b"tension", addr=1, wired=15),
    )

    out = fw_link.unpack(fw_abi.rpc_sys_devices_ret, bytes(head) + bytes(devs))
    assert out.count == 2
    assert [d.name.decode() for d in out.devs] == ["capstan", "tension"]


def test_a_reply_truncated_at_its_tail_still_unpacks():
    ret = fw_abi.rpc_relay_send_ret(outcome=fw_abi.RPC_RX_TIMEOUT, count=0)
    short = bytes(ret)[: fw_abi.rpc_relay_send_ret.rx.offset]
    assert len(short) < ctypes.sizeof(fw_abi.rpc_relay_send_ret)

    out = fw_link.unpack(fw_abi.rpc_relay_send_ret, short)
    assert out.outcome == fw_abi.RPC_RX_TIMEOUT
    assert out.count == 0


def test_a_count_the_payload_does_not_back_is_refused():
    head = fw_abi.rpc_sys_devices_ret(count=4)
    with pytest.raises(fw_link.LinkError):
        fw_link.unpack(fw_abi.rpc_sys_devices_ret, bytes(head))


# ── The surface derived from the enums ───────────────────────────────────────


def test_the_namespaces_are_the_ones_with_methods():
    assert set(fw_link.namespaces()) == {"sys", "relay", "raw"}


def test_every_method_carries_at_least_one_payload():
    for _, specs in fw_link.namespaces().values():
        for spec in specs.values():
            assert spec.args is not None or spec.ret is not None, spec.name


def test_no_terminator_became_a_method():
    for _, specs in fw_link.namespaces().values():
        assert "count" not in specs


def test_a_method_finds_the_payloads_its_own_name_predicts():
    _, raw = fw_link.namespaces()["raw"]
    assert raw["poll_health"].args is fw_abi.rpc_dev_args
    assert raw["poll_health"].ret is fw_abi.rpc_raw_poll_health_ret
    assert raw["enable"].ret is None

    _, relay = fw_link.namespaces()["relay"]
    assert relay["send"].method == fw_abi.RPC_RELAY_SEND
    assert relay["send"].fields == ("idx", "reply_len", "tx")

    _, sys_ns = fw_link.namespaces()["sys"]
    assert sys_ns["version"].args is None
    assert sys_ns["version"].ret is fw_abi.rpc_sys_version_ret


# ── Driving the link ─────────────────────────────────────────────────────────


def test_a_link_names_a_port_or_carries_a_stream():
    with pytest.raises(fw_link.LinkError):
        fw_link.FirmwareLink()
    with pytest.raises(fw_link.LinkError):
        fw_link.FirmwareLink("/dev/null", stream=FakeFirmware())


def test_a_link_reads_from_the_moment_it_exists():
    firmware, link = linked(echo_state)
    with link:
        assert link.sys.state().device_count == 3
    assert firmware.closed


def test_a_call_returns_what_the_reply_carried():
    firmware, link = linked(echo_state)
    with link:
        state = link.sys.state()

    assert state.uptime_ms == 1234
    assert state.device_count == 3
    assert firmware.requests[0].header.ns == fw_abi.RPC_NS_SYS
    assert firmware.requests[0].header.method == fw_abi.RPC_SYS_STATE


def test_arguments_travel_positionally_and_by_name():
    def answer(_firmware, frame):
        value = fw_abi.rpc_raw_read_ret(value=0xDEADBEEF)
        return [seal_reply(frame.header.id, fw_abi.RPC_OK, bytes(value))]

    firmware, link = linked(answer)
    with link:
        assert link.raw.read(1, fw_abi.TMC2209_GCONF).value == 0xDEADBEEF
        assert link.raw.read(idx=1, reg=fw_abi.TMC2209_GCONF).value == 0xDEADBEEF

    for request in firmware.requests:
        args = fw_abi.rpc_raw_read_args.from_buffer_copy(request.payload)
        assert (args.idx, args.reg) == (1, fw_abi.TMC2209_GCONF)


def test_a_flexible_argument_reaches_the_wire_whole():
    datagram = bytes(range(fw_abi.TMC2209_WRITE_LEN))

    def answer(_firmware, frame):
        ret = fw_abi.rpc_relay_send_ret(outcome=fw_abi.RPC_OK, count=0)
        payload = bytes(ret)[: fw_abi.rpc_relay_send_ret.rx.offset]
        return [seal_reply(frame.header.id, fw_abi.RPC_OK, payload)]

    firmware, link = linked(answer)
    with link:
        out = link.relay.send(0, 0, datagram)

    assert out.outcome == fw_abi.RPC_OK
    sent = firmware.requests[0].payload
    base = ctypes.sizeof(fw_abi.rpc_relay_send_args)
    assert sent[base:] == datagram


def test_a_failing_status_raises_the_exception_that_names_it():
    def answer(_firmware, frame):
        return [seal_reply(frame.header.id, fw_abi.RPC_NO_BACKEND)]

    _, link = linked(answer)
    with link, pytest.raises(fw_abi.RpcNoBackend) as caught:
        link.raw.poll_health(0)

    assert caught.value.status == fw_abi.RPC_NO_BACKEND


def test_a_log_between_the_request_and_its_reply_reaches_the_sink():
    seen = []

    def answer(_firmware, frame):
        return [
            seal_log(3, 42, "bringing up capstan"),
            *echo_state(_firmware, frame),
            seal_log(3, 43, "capstan ready"),
        ]

    _, link = linked(answer, on_log=seen.append)
    with link:
        assert link.sys.state().uptime_ms == 1234
        assert wait_until(lambda: len(seen) == 2)

    assert [record.text for record in seen] == [
        "bringing up capstan",
        "capstan ready",
    ]
    assert seen[0].uptime_ms == 42


def test_a_reply_nobody_waits_for_is_counted_and_discarded():
    firmware, link = linked()
    with link:
        firmware.push(seal_reply(0xBEEF, fw_abi.RPC_OK))
        assert wait_until(lambda: link.unmatched == 1)


def test_a_frame_that_does_not_open_is_counted_and_discarded():
    firmware, link = linked()
    with link:
        firmware.push(b"\x05ab\x00")
        assert wait_until(lambda: link.malformed == 1)


def test_silence_ends_the_call_rather_than_the_process():
    _, link = linked()
    with link, pytest.raises(fw_link.LinkTimeout):
        link.sys.state(timeout=0.05)


def test_an_abandoned_request_frees_its_id():
    firmware, link = linked()
    with link:
        with pytest.raises(fw_link.LinkTimeout):
            link.sys.state(timeout=0.05)
        firmware.push(seal_reply(firmware.requests[0].header.id, fw_abi.RPC_OK))
        assert wait_until(lambda: link.unmatched == 1)


def test_every_request_carries_its_own_id():
    firmware, link = linked(echo_state)
    with link:
        for _ in range(4):
            link.sys.state()

    ids = [request.header.id for request in firmware.requests]
    assert len(set(ids)) == len(ids)


def test_a_closed_link_refuses_new_calls():
    _, link = linked(echo_state)
    link.close()
    with pytest.raises(fw_link.LinkClosed):
        link.sys.state()


def test_an_unknown_method_is_an_attribute_error():
    _, link = linked()
    with link, pytest.raises(AttributeError):
        link.raw.rewind()


def test_an_unknown_namespace_is_an_attribute_error():
    _, link = linked()
    with link, pytest.raises(AttributeError):
        link.film.advance()


def test_an_argument_the_method_does_not_take_is_refused():
    _, link = linked(echo_state)
    with link:
        with pytest.raises(TypeError):
            link.raw.read(0, fw_abi.TMC2209_GCONF, 3)
        with pytest.raises(TypeError):
            link.raw.read(0, idx=1)
        with pytest.raises(TypeError):
            link.raw.read(idx=0, register=1)
