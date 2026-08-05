"""Carries frames to the firmware and back, and pairs each reply to its request."""

import ctypes
import itertools
import threading
from typing import Any, NamedTuple

from transport import fw_abi

# ── Names ────────────────────────────────────────────────────────────────────

DELIMITER = b"\x00"
DEFAULT_TIMEOUT = 1.0
DEFAULT_BAUDRATE = 115200
READ_POLL = 0.05
ID_MASK = 0xFFFF


# ── How this fails ───────────────────────────────────────────────────────────


class LinkError(Exception):
    """Anything that stops a call from reaching an answer."""

    pass


class LinkTimeout(LinkError):
    """The board said nothing in time."""

    pass


class LinkClosed(LinkError):
    """The link went away with the call still in flight."""

    pass


# ── Bounds and shapes ────────────────────────────────────────────────────────


def cobs_encoded_max(length: int) -> int:
    """Return the worst case encoded length, the delimiter not counted."""
    return length + length // 254 + 1


MAX_ENCODED = cobs_encoded_max(fw_abi.RPC_MAX_FRAME)

HEADERS = {
    fw_abi.RPC_FRAME_REQ: fw_abi.rpc_req_hdr_t,
    fw_abi.RPC_FRAME_REP: fw_abi.rpc_rep_hdr_t,
    fw_abi.RPC_FRAME_LOG: fw_abi.rpc_log_hdr_t,
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
    if len(payload) > fw_abi.RPC_MAX_PAYLOAD:
        raise LinkError(f"payload of {len(payload)} bytes exceeds the frame")
    buf = fw_abi.rpc_buf_t()
    if payload:
        ctypes.memmove(ctypes.byref(buf, fw_abi.RPC_HDR_LEN), payload, len(payload))
    length = fw_abi.rpc_frame_seal_req(buf, request_id, ns, method, len(payload))
    if length == 0:
        raise LinkError(f"the firmware refused to seal {len(payload)} bytes")
    return bytes(buf.bytes[:length])


def encode(frame: bytes) -> bytes:
    """Return the frame as bytes with no zero in them, delimiter appended."""
    src = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
    capacity = cobs_encoded_max(len(frame))
    dst = (ctypes.c_uint8 * capacity)()
    written = fw_abi.cobs_encode(src, len(frame), dst, capacity)
    if written == 0:
        raise LinkError(f"cobs_encode refused {len(frame)} bytes")
    return bytes(dst[:written]) + DELIMITER


def open_frame(run: bytes) -> Frame | None:
    """Return what the run decodes to, or None if it is not a frame."""
    buf = fw_abi.rpc_buf_t()
    src = (ctypes.c_uint8 * len(run)).from_buffer_copy(run)
    decoded = fw_abi.cobs_decode(src, len(run), buf.bytes, fw_abi.RPC_MAX_FRAME)
    if decoded == 0:
        return None

    view = fw_abi.rpc_view_t()
    if not fw_abi.rpc_frame_open(ctypes.byref(buf), decoded, ctypes.byref(view)):
        return None

    header_type = HEADERS[view.type]
    header = header_type.from_buffer_copy(bytes(buf.bytes[: fw_abi.RPC_HDR_LEN]))
    payload = b""
    if view.payload_len:
        payload = ctypes.string_at(view.payload, view.payload_len)
    return Frame(view.type, header, payload)


# ── Payloads that end in a flexible array ────────────────────────────────────


def _array(elem: Any, count: int) -> Any:
    """Return the ctypes array type for the element and count given."""
    return elem * count


def pack(struct_type: type, values: dict[str, Any]) -> bytes:
    """Return the payload bytes, sizing any flexible member from its sequence."""
    flex = fw_abi.FLEX.get(struct_type)
    if flex is None:
        return bytes(struct_type(**values))

    values = dict(values)
    items = list(values.pop(flex.field, ()))
    head = struct_type(**values)
    setattr(head, flex.count_field, len(items))
    return bytes(head) + bytes(_array(flex.elem, len(items))(*items))


def unpack(struct_type: type, payload: bytes) -> Any:
    """Return the payload as its struct, with a flexible member attached."""
    base = ctypes.sizeof(struct_type)
    if len(payload) < base:
        payload = payload + bytes(base - len(payload))

    head = struct_type.from_buffer_copy(payload[:base])
    flex = fw_abi.FLEX.get(struct_type)
    if flex is not None:
        count = getattr(head, flex.count_field)
        width = ctypes.sizeof(flex.elem)
        tail = payload[base : base + count * width]
        if len(tail) != count * width:
            raise LinkError(f"{struct_type.__name__} claims {count} it did not send")
        setattr(head, flex.field, list(_array(flex.elem, count).from_buffer_copy(tail)))
    return head


# ── The surface derived from the enums ───────────────────────────────────────


class MethodSpec(NamedTuple):
    """One callable method, and the payload types its own name predicts."""

    name: str
    ns: int
    method: int
    args: type | None
    ret: type | None
    fields: tuple[str, ...]


def _positional_fields(args_type: type | None) -> tuple[str, ...]:
    """Return the arguments a caller may pass by position, in order."""
    if args_type is None:
        return ()
    declared = getattr(args_type, "_fields_", [])
    names = [name for name, *_ in declared if not name.startswith("_pad")]
    flex = fw_abi.FLEX.get(args_type)
    if flex is not None:
        names = [n for n in names if n != flex.count_field] + [flex.field]
    return tuple(names)


def _methods(stem: str, ns: int, method_enum: Any) -> dict[str, MethodSpec]:
    """Return one namespace's methods, keyed by the name they answer to."""
    specs: dict[str, MethodSpec] = {}
    for member in method_enum:
        if member.name.endswith("_COUNT"):
            continue
        payload_stem = member.name.lower()
        args = getattr(fw_abi, f"{payload_stem}_args", None)
        ret = getattr(fw_abi, f"{payload_stem}_ret", None)
        attr = member.name.removeprefix(f"RPC_{stem}_").lower()
        specs[attr] = MethodSpec(
            name=f"{stem.lower()}.{attr}",
            ns=ns,
            method=int(member),
            args=args,
            ret=ret,
            fields=_positional_fields(args),
        )
    return specs


def namespaces() -> dict[str, tuple[int, dict[str, MethodSpec]]]:
    """Return every namespace that has methods, derived from the enums."""
    found: dict[str, tuple[int, dict[str, MethodSpec]]] = {}
    for member in fw_abi.rpc_ns_t:
        if member.name.endswith("_COUNT"):
            continue
        stem = member.name.removeprefix("RPC_NS_")
        method_enum = getattr(fw_abi, f"rpc_{stem.lower()}_method_t", None)
        if method_enum is None:
            continue
        found[stem.lower()] = (int(member), _methods(stem, int(member), method_enum))
    return found


class Namespace:
    """One namespace's methods, reached as attributes of the link."""

    def __init__(self, link: "FirmwareLink", specs: dict[str, MethodSpec]) -> None:
        """Bind these methods to the link that will carry them."""
        self._link = link
        self._specs = specs

    def __getattr__(self, name: str) -> Any:
        """Return the named method, bound to this link, or say there is none."""
        spec = self._specs.get(name)
        if spec is None:
            raise AttributeError(name)

        def invoke(*args: Any, **kwargs: Any) -> Any:
            """Send this method's request and return what the reply carried."""
            return self._link.invoke(spec, args, kwargs)

        invoke.__name__ = name
        return invoke

    def __dir__(self) -> list[str]:
        """Return the attributes plus every method name, so completion sees them."""
        return [*super().__dir__(), *self._specs]


# ── Requests in flight ───────────────────────────────────────────────────────


class _Pending:
    """One request waiting for the reply that carries its id."""

    __slots__ = ("event", "payload", "status")

    def __init__(self) -> None:
        """Start unanswered, holding the event its caller will wait on."""
        self.event = threading.Event()
        self.status: int | None = None
        self.payload = b""


class FirmwareLink:
    """A firmware on the other end of a port, and the calls it serves."""

    def __init__(
        self,
        port: str | None = None,
        *,
        stream: Any = None,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
        on_log: Any = None,
    ) -> None:
        """Open the port, or take a stream, and start reading either way."""
        self._namespaces: dict[str, Namespace] = {}
        if (port is None) == (stream is None):
            raise LinkError("name a port or pass a stream, not both and not neither")
        if stream is None:
            import serial

            stream = serial.Serial(port, baudrate, timeout=READ_POLL)

        self._stream = stream
        self._timeout = timeout
        self._on_log = on_log
        self._pending: dict[int, _Pending] = {}
        self._lock = threading.Lock()
        self._writing = threading.Lock()
        self._ids = itertools.count()
        self._stop = threading.Event()
        self._splitter = FrameSplitter()
        self._reader: threading.Thread | None = None
        self.unmatched = 0
        self.malformed = 0
        self._namespaces = {
            name: Namespace(self, specs) for name, (_, specs) in namespaces().items()
        }
        self._start()

    def __getattr__(self, name: str) -> Namespace:
        """Return the named namespace, or say this build serves none by that name."""
        namespace = self.__dict__.get("_namespaces", {}).get(name)
        if namespace is None:
            raise AttributeError(name)
        return namespace

    def __dir__(self) -> list[str]:
        """Return the attributes plus every namespace, so completion sees them."""
        return [*super().__dir__(), *self._namespaces]

    def __enter__(self) -> "FirmwareLink":
        """Return the link, already reading."""
        return self

    def __exit__(self, *_: Any) -> None:
        """Close the link however the block ended."""
        self.close()

    def _start(self) -> None:
        """Start the one thread that owns reading, if it is not running."""
        if self._reader is not None:
            return
        self._stop.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="fw_link", daemon=True
        )
        self._reader.start()

    def close(self) -> None:
        """Stop reading, drop the port, and release anyone still waiting."""
        self._stop.set()
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.join(timeout=2.0)
        try:
            self._stream.close()
        except Exception:
            pass
        with self._lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for pending in waiting:
            pending.event.set()

    def _read_loop(self) -> None:
        """Pull bytes for as long as the link is open, handing on whole frames."""
        while not self._stop.is_set():
            try:
                waiting = getattr(self._stream, "in_waiting", 0)
                data = self._stream.read(max(1, waiting))
            except Exception:
                break
            if not data:
                continue
            for run in self._splitter.feed(data):
                self._deliver(run)

    def _deliver(self, run: bytes) -> None:
        """Route one frame to its caller, to the log sink, or to a counter."""
        frame = open_frame(run)
        if frame is None:
            self.malformed += 1
            return

        if frame.type == fw_abi.RPC_FRAME_LOG:
            if self._on_log is not None:
                self._on_log(
                    LogRecord(
                        frame.header.level,
                        frame.header.uptime_ms,
                        frame.payload.decode("utf-8", "replace"),
                    )
                )
            return

        if frame.type != fw_abi.RPC_FRAME_REP:
            self.unmatched += 1
            return

        with self._lock:
            pending = self._pending.pop(frame.header.id, None)
        if pending is None:
            self.unmatched += 1
            return

        pending.status = frame.header.status
        pending.payload = frame.payload
        pending.event.set()

    def _reserve(self) -> tuple[int, _Pending]:
        """Return a request id no reply is pending on, and the slot to wait at."""
        with self._lock:
            for _ in range(ID_MASK + 1):
                request_id = next(self._ids) & ID_MASK
                if request_id not in self._pending:
                    pending = _Pending()
                    self._pending[request_id] = pending
                    return request_id, pending
        raise LinkError("every request id is in flight")

    def call(
        self,
        ns: int,
        method: int,
        payload: bytes = b"",
        timeout: float | None = None,
    ) -> bytes:
        """Send one request and return the payload of the reply that answers it."""
        if self._stop.is_set():
            raise LinkClosed("the link is closed")

        request_id, pending = self._reserve()
        try:
            encoded = encode(seal_request(request_id, ns, method, payload))
            with self._writing:
                self._stream.write(encoded)
            deadline = self._timeout if timeout is None else timeout
            if not pending.event.wait(deadline):
                raise LinkTimeout(
                    f"no reply to request {request_id} within {deadline}s"
                )
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

        if pending.status is None:
            raise LinkClosed("the link closed while the request was in flight")

        fw_abi.raise_for_status(pending.status)
        return pending.payload

    def invoke(
        self,
        spec: MethodSpec,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Call a method by its spec, packing arguments and unpacking the reply."""
        if len(args) > len(spec.fields):
            raise TypeError(
                f"{spec.name} takes {len(spec.fields)} arguments, got {len(args)}"
            )

        kwargs = dict(kwargs)
        timeout = None
        if "timeout" not in spec.fields:
            timeout = kwargs.pop("timeout", None)

        values = dict(zip(spec.fields, args, strict=False))
        for name in kwargs:
            if name in values:
                raise TypeError(f"{spec.name} got {name} twice")
        values.update(kwargs)

        unknown = set(values) - set(spec.fields)
        if unknown:
            raise TypeError(f"{spec.name} has no argument {', '.join(sorted(unknown))}")

        payload = pack(spec.args, values) if spec.args is not None else b""
        reply = self.call(spec.ns, spec.method, payload, timeout)
        if spec.ret is None:
            return None
        return unpack(spec.ret, reply)


# ── Finding the board ────────────────────────────────────────────────────────


def find_port() -> str:
    """Return the one attached ESP32's port, or say why there is no one answer."""
    from transport.temp_esp32_finder import find_candidates

    matches = [port.device for port, match in find_candidates() if match is not None]
    if not matches:
        raise LinkError("no ESP32-like USB device found")
    if len(matches) > 1:
        raise LinkError(f"several candidates, name one: {', '.join(matches)}")
    return matches[0]
