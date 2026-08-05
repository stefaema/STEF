import ctypes
import itertools
import threading
from typing import Any, NamedTuple

from transport import fw_abi

DELIMITER = b"\x00"
DEFAULT_TIMEOUT = 1.0
ID_MASK = 0xFFFF


class LinkError(Exception):
    pass


class LinkTimeout(LinkError):
    pass


class LinkClosed(LinkError):
    pass


def cobs_encoded_max(length: int) -> int:
    return length + length // 254 + 1


MAX_ENCODED = cobs_encoded_max(fw_abi.RPC_MAX_FRAME)

HEADERS = {
    fw_abi.RPC_FRAME_REQ: fw_abi.rpc_req_hdr_t,
    fw_abi.RPC_FRAME_REP: fw_abi.rpc_rep_hdr_t,
    fw_abi.RPC_FRAME_LOG: fw_abi.rpc_log_hdr_t,
}


class Frame(NamedTuple):
    type: int
    header: Any
    payload: bytes


class LogRecord(NamedTuple):
    level: int
    uptime_ms: int
    text: str


class FrameSplitter:
    def __init__(self, limit: int = MAX_ENCODED) -> None:
        self._limit = limit
        self._run = bytearray()
        self._resync = False
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
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


def seal_request(request_id: int, ns: int, method: int, payload: bytes) -> bytes:
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
    src = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
    capacity = cobs_encoded_max(len(frame))
    dst = (ctypes.c_uint8 * capacity)()
    written = fw_abi.cobs_encode(src, len(frame), dst, capacity)
    if written == 0:
        raise LinkError(f"cobs_encode refused {len(frame)} bytes")
    return bytes(dst[:written]) + DELIMITER


def open_frame(run: bytes) -> Frame | None:
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


def _array(elem: Any, count: int) -> Any:
    return elem * count


def pack(struct_type: type, values: dict[str, Any]) -> bytes:
    flex = fw_abi.FLEX.get(struct_type)
    if flex is None:
        return bytes(struct_type(**values))

    values = dict(values)
    items = list(values.pop(flex.field, ()))
    head = struct_type(**values)
    setattr(head, flex.count_field, len(items))
    return bytes(head) + bytes(_array(flex.elem, len(items))(*items))


def unpack(struct_type: type, payload: bytes) -> Any:
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


class MethodSpec(NamedTuple):
    name: str
    ns: int
    method: int
    args: type | None
    ret: type | None
    fields: tuple[str, ...]


def _positional_fields(args_type: type | None) -> tuple[str, ...]:
    if args_type is None:
        return ()
    declared = getattr(args_type, "_fields_", [])
    names = [name for name, *_ in declared if not name.startswith("_pad")]
    flex = fw_abi.FLEX.get(args_type)
    if flex is not None:
        names = [n for n in names if n != flex.count_field] + [flex.field]
    return tuple(names)


def _methods(stem: str, ns: int, method_enum: Any) -> dict[str, MethodSpec]:
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
    def __init__(self, link: "Link", specs: dict[str, MethodSpec]) -> None:
        self._link = link
        self._specs = specs

    def __getattr__(self, name: str) -> Any:
        spec = self._specs.get(name)
        if spec is None:
            raise AttributeError(name)

        def invoke(*args: Any, **kwargs: Any) -> Any:
            return self._link.invoke(spec, args, kwargs)

        invoke.__name__ = name
        return invoke

    def __dir__(self) -> list[str]:
        return [*super().__dir__(), *self._specs]


class _Pending:
    __slots__ = ("event", "payload", "status")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.status: int | None = None
        self.payload = b""


class Link:
    def __init__(
        self,
        stream: Any,
        timeout: float = DEFAULT_TIMEOUT,
        on_log: Any = None,
    ) -> None:
        self._namespaces: dict[str, Namespace] = {}
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

    @classmethod
    def open(cls, port: str, baudrate: int = 115200, **kwargs: Any) -> "Link":
        import serial

        stream = serial.Serial(port, baudrate, timeout=0.05)
        link = cls(stream, **kwargs)
        link.start()
        return link

    def __getattr__(self, name: str) -> Namespace:
        namespace = self.__dict__.get("_namespaces", {}).get(name)
        if namespace is None:
            raise AttributeError(name)
        return namespace

    def __dir__(self) -> list[str]:
        return [*super().__dir__(), *self._namespaces]

    def __enter__(self) -> "Link":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._reader is not None:
            return
        self._stop.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="fw_link", daemon=True
        )
        self._reader.start()

    def close(self) -> None:
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


def find_port() -> str:
    from transport.temp_esp32_finder import find_candidates

    matches = [port.device for port, match in find_candidates() if match is not None]
    if not matches:
        raise LinkError("no ESP32-like USB device found")
    if len(matches) > 1:
        raise LinkError(f"several candidates, name one: {', '.join(matches)}")
    return matches[0]
