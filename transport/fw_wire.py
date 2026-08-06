"""Frames on and off a byte stream, using the firmware's own codec."""

import ctypes
from typing import Any, NamedTuple

from transport import fw_api

DELIMITER = b"\x00"


class WireError(fw_api.TransportError):
    """A frame that cannot be built, or bytes that cannot be one."""


def cobs_encoded_max(length: int) -> int:
    """Return the worst case encoded length, the delimiter not counted."""
    return length + length // 254 + 1


MAX_ENCODED = cobs_encoded_max(fw_api.RPC_MAX_FRAME)

HEADERS = {
    fw_api.RPC_FRAME_REQ: fw_api.rpc_req_hdr_t,
    fw_api.RPC_FRAME_REP: fw_api.rpc_rep_hdr_t,
    fw_api.RPC_FRAME_LOG: fw_api.rpc_log_hdr_t,
}


class Frame(NamedTuple):
    """One decoded frame: its kind, its header, and the bytes after it."""

    type: int
    header: Any
    payload: bytes


class LogRecord(NamedTuple):
    """One log line the firmware sent unprompted."""

    level: int
    uptime_ms: int
    text: str


# ── Finding frames in a stream of bytes ──────────────────────────────────────


class FrameSplitter:
    """Turns a stream of bytes into whole frames, and resyncs after a bad one."""

    def __init__(self, limit: int = MAX_ENCODED) -> None:
        """Start with an empty run and no frame to resync past."""
        self._limit = limit
        self._run = bytearray()
        self._resync = False
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
        """Return every frame that the delimiter completed in this chunk."""
        runs: list[bytes] = []
        for byte in data:
            if byte == 0:
                if self._run and not self._resync:
                    runs.append(bytes(self._run))
                self._run.clear()
                self._resync = False
                continue
            if self._resync:
                continue
            self._run.append(byte)
            if len(self._run) > self._limit:
                self._run.clear()
                self._resync = True
                self.dropped += 1
        return runs


# ── The codec, which is the firmware's own ───────────────────────────────────


def seal_request(request_id: int, ns: int, method: int, payload: bytes) -> bytes:
    """Return a request frame, header and CRC put on by the firmware's own code."""
    if len(payload) > fw_api.RPC_MAX_PAYLOAD:
        raise WireError(f"payload of {len(payload)} bytes exceeds the frame")
    buf = fw_api.rpc_buf_t()
    if payload:
        ctypes.memmove(ctypes.byref(buf, fw_api.RPC_HDR_LEN), payload, len(payload))
    length = fw_api.rpc_frame_seal_req(buf, request_id, ns, method, len(payload))
    if length == 0:
        raise WireError(f"the firmware refused to seal {len(payload)} bytes")
    return bytes(buf.bytes[:length])


def encode(frame: bytes) -> bytes:
    """Return the frame as bytes with no zero in them, delimiter appended."""
    src = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
    capacity = cobs_encoded_max(len(frame))
    dst = (ctypes.c_uint8 * capacity)()
    written = fw_api.cobs_encode(src, len(frame), dst, capacity)
    if written == 0:
        raise WireError(f"cobs_encode refused {len(frame)} bytes")
    return bytes(dst[:written]) + DELIMITER


def open_frame(run: bytes) -> Frame | None:
    """Return what the run decodes to, or None if it is not a frame."""
    buf = fw_api.rpc_buf_t()
    src = (ctypes.c_uint8 * len(run)).from_buffer_copy(run)
    decoded = fw_api.cobs_decode(src, len(run), buf.bytes, fw_api.RPC_MAX_FRAME)
    if decoded == 0:
        return None

    view = fw_api.rpc_view_t()
    if not fw_api.rpc_frame_open(ctypes.byref(buf), decoded, ctypes.byref(view)):
        return None

    header_type = HEADERS[view.type]
    header = header_type.from_buffer_copy(bytes(buf.bytes[: fw_api.RPC_HDR_LEN]))
    payload = b""
    if view.payload_len:
        payload = ctypes.string_at(view.payload, view.payload_len)
    return Frame(view.type, header, payload)


def log_record(frame: Frame) -> LogRecord:
    """Return a log frame as the record a sink is given."""
    return LogRecord(
        frame.header.level,
        frame.header.uptime_ms,
        frame.payload.decode("utf-8", "replace"),
    )
