import ctypes
import threading
import time

import pytest

from shared import fw_api
from transport import fw_link, fw_wire

TIMEOUT = 0.5


def seal_reply(request_id, status, payload=b""):
    buf = fw_api.rpc_buf_t()
    if payload:
        ctypes.memmove(ctypes.byref(buf, fw_api.RPC_HDR_LEN), payload, len(payload))
    length = fw_api.rpc_frame_seal_rep(buf, request_id, status, len(payload))
    return fw_wire.encode(bytes(buf.bytes[:length]))


def seal_log(level, uptime_ms, text):
    buf = fw_api.rpc_buf_t()
    payload = text.encode()
    ctypes.memmove(ctypes.byref(buf, fw_api.RPC_HDR_LEN), payload, len(payload))
    length = fw_api.rpc_frame_seal_log(buf, level, uptime_ms, len(payload))
    return fw_wire.encode(bytes(buf.bytes[:length]))


class FakeFirmware:
    def __init__(self, answer=None):
        self.answer = answer
        self.requests = []
        self.closed = False
        self._out = bytearray()
        self._splitter = fw_wire.FrameSplitter()
        self._cv = threading.Condition()

    def push(self, data):
        with self._cv:
            self._out += data
            self._cv.notify_all()

    def write(self, data):
        for run in self._splitter.feed(data):
            frame = fw_wire.open_frame(run)
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
    ret = fw_api.rpc_sys_state_ret(
        uptime_ms=1234, device_count=3, mode=fw_api.RPC_MODE_IDLE, ready=1
    )
    return [seal_reply(frame.header.id, fw_api.RPC_OK, bytes(ret))]


def linked(answer=None, timeout=TIMEOUT, **kwargs):
    firmware = FakeFirmware(answer)
    link = fw_link.FirmwareLink(stream=firmware, timeout=timeout, **kwargs)
    return firmware, link


def wait_until(predicate, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


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
    assert firmware.requests[0].header.ns == fw_api.RPC_NS_SYS
    assert firmware.requests[0].header.method == fw_api.RPC_SYS_STATE


def test_arguments_travel_positionally_and_by_name():
    def answer(_firmware, frame):
        value = fw_api.rpc_raw_read_ret(value=0xDEADBEEF)
        return [seal_reply(frame.header.id, fw_api.RPC_OK, bytes(value))]

    firmware, link = linked(answer)
    with link:
        assert link.raw.read(1, fw_api.TMC2209_GCONF).value == 0xDEADBEEF
        assert link.raw.read(idx=1, reg=fw_api.TMC2209_GCONF).value == 0xDEADBEEF

    for request in firmware.requests:
        args = fw_api.rpc_raw_read_args.from_buffer_copy(request.payload)
        assert (args.idx, args.reg) == (1, fw_api.TMC2209_GCONF)


def test_a_reply_reaches_the_caller_as_python_and_not_as_ctypes():
    _, link = linked(echo_state)
    with link:
        state = link.sys.state()

    assert state == fw_api.namespaces()["sys"]["state"].ret(
        uptime_ms=1234, device_count=3, mode=fw_api.RpcMode.IDLE, ready=True
    )
    assert state.mode is fw_api.RpcMode.RPC_MODE_IDLE
    assert state.ready is True
    assert not isinstance(state, ctypes.Structure)


def test_an_enum_argument_puts_the_byte_a_bare_int_would_have():
    def answer(_firmware, frame):
        return [seal_reply(frame.header.id, fw_api.RPC_OK)]

    firmware, link = linked(answer)
    with link:
        link.raw.move(idx=1, dir=fw_api.Tmc2209Level.HIGH, shaft=True, pulses=4000)
        link.raw.move(idx=1, dir=1, shaft=1, pulses=4000)

    by_hand = fw_api.rpc_raw_move_args(idx=1, dir=1, shaft=1, pulses=4000)
    assert [request.payload for request in firmware.requests] == [bytes(by_hand)] * 2


def test_a_device_table_arrives_as_a_list_of_dataclasses():
    def answer(_firmware, frame):
        head = fw_api.rpc_sys_devices_ret(count=1)
        one = fw_api.rpc_dev_info_t(
            name=b"capstan", addr=0, wired=fw_api.TMC2209_LINES_ALL, has_uart=1
        )
        return [seal_reply(frame.header.id, fw_api.RPC_OK, bytes(head) + bytes(one))]

    _, link = linked(answer)
    with link:
        (capstan,) = link.sys.devices().devs

    assert capstan.name == b"capstan"
    assert capstan.has_uart is True
    assert capstan.wired is fw_api.Tmc2209LineMask(fw_api.TMC2209_LINES_ALL)


def test_a_flexible_argument_reaches_the_wire_whole():
    datagram = bytes(range(fw_api.TMC2209_WRITE_LEN))

    def answer(_firmware, frame):
        ret = fw_api.rpc_relay_send_ret(outcome=fw_api.RPC_OK, count=0)
        payload = bytes(ret)[: fw_api.rpc_relay_send_ret.rx.offset]
        return [seal_reply(frame.header.id, fw_api.RPC_OK, payload)]

    firmware, link = linked(answer)
    with link:
        out = link.relay.send(0, 0, datagram)

    assert out.outcome == fw_api.RPC_OK
    sent = firmware.requests[0].payload
    base = ctypes.sizeof(fw_api.rpc_relay_send_args)
    assert sent[base:] == datagram


def test_a_failing_status_raises_the_exception_that_names_it():
    def answer(_firmware, frame):
        return [seal_reply(frame.header.id, fw_api.RPC_NO_BACKEND)]

    _, link = linked(answer)
    with link, pytest.raises(fw_api.RpcNoBackend) as caught:
        link.raw.poll_health(0)

    assert caught.value.status == fw_api.RPC_NO_BACKEND


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
        firmware.push(seal_reply(0xBEEF, fw_api.RPC_OK))
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
        firmware.push(seal_reply(firmware.requests[0].header.id, fw_api.RPC_OK))
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
            link.raw.read(0, fw_api.TMC2209_GCONF, 3)
        with pytest.raises(TypeError):
            link.raw.read(0, idx=1)
        with pytest.raises(TypeError):
            link.raw.read(idx=0, register=1)


# ── What the broker guarantees ───────────────────────────────────────────────


def test_only_one_request_is_ever_on_the_wire():
    depth = []

    def answer(firmware, frame):
        depth.append(len(firmware.requests))
        return echo_state(firmware, frame)

    _, link = linked(answer)
    with link:
        threads = [threading.Thread(target=link.sys.state) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]

    assert depth == [1, 2, 3, 4, 5, 6]


def test_a_timeout_measures_this_call_and_not_the_queue():
    def answer(_firmware, frame):
        time.sleep(0.15)
        return echo_state(_firmware, frame)

    _, link = linked(answer, timeout=0.4)
    with link:
        started = time.monotonic()
        threads = [threading.Thread(target=link.sys.state) for _ in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]

    assert time.monotonic() - started > 0.5


def test_a_log_sink_never_runs_on_the_reader():
    threads = []
    seen = threading.Event()

    def sink(_record):
        threads.append(threading.current_thread().name)
        seen.set()

    firmware, link = linked(echo_state, on_log=sink)
    with link:
        firmware.push(seal_log(3, 1, "hello"))
        assert seen.wait(TIMEOUT)
        assert link.sys.state().uptime_ms == 1234

    assert threads == ["fw_logs"]


def test_a_sink_that_raises_costs_one_record_and_nothing_else():
    def sink(_record):
        raise RuntimeError("the sink is broken")

    firmware, link = linked(echo_state, on_log=sink)
    with link:
        firmware.push(seal_log(3, 1, "boom"))
        assert wait_until(lambda: link.dropped == 1)
        assert link.sys.state().uptime_ms == 1234
