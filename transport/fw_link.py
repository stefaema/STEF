"""A firmware on the other end of a port, assembled from four collaborators."""

import itertools
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, NamedTuple

from transport import fw_api, fw_wire

# ── Names ────────────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 1.0
DEFAULT_BAUDRATE = 115200
READ_POLL = 0.05
LOG_DEPTH = 256
JOIN_TIMEOUT = 2.0
ID_MASK = 0xFFFF


# ── How this fails ───────────────────────────────────────────────────────────


class LinkError(fw_api.TransportError):
    """Anything that stops a call from reaching an answer."""


class LinkTimeout(LinkError):
    """The board said nothing in time."""


class LinkClosed(LinkError):
    """The link went away with the call still in flight."""


# ── Reading the port ─────────────────────────────────────────────────────────


class FrameReader:
    """Owns the stream and the splitter, and hands each whole frame to a router."""

    def __init__(self, stream: Any, route: Callable[[fw_wire.Frame], None]) -> None:
        """Take the stream to read and the router that every frame goes to."""
        self._stream = stream
        self._route = route
        self._splitter = fw_wire.FrameSplitter()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.malformed = 0

    @property
    def dropped(self) -> int:
        """Return how many runs exceeded the bound, so delimiters had gone missing."""
        return self._splitter.dropped

    def start(self) -> None:
        """Start the one thread that owns reading."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fw_read", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish and wait for it."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=JOIN_TIMEOUT)

    def _loop(self) -> None:
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
                frame = fw_wire.open_frame(run)
                if frame is None:
                    self.malformed += 1
                    continue
                self._route(frame)


# ── Carrying logs off the read path ──────────────────────────────────────────


class LogForwarder:
    """Carries log records to a sink on its own thread, never on the reader's."""

    def __init__(self, sink: Any = None, depth: int = LOG_DEPTH) -> None:
        """Take the sink each record goes to, and how many may wait for it."""
        self._sink = sink
        self._queue: queue.Queue[fw_wire.LogRecord] = queue.Queue(maxsize=depth)
        self._thread: threading.Thread | None = None
        self.dropped = 0

    def offer(self, record: fw_wire.LogRecord) -> None:
        """Hand over a record without ever blocking, dropping the oldest if full."""
        if self._sink is None:
            return
        while True:
            try:
                self._queue.put_nowait(record)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    return

    def start(self) -> None:
        """Start the one thread that drains to the sink."""
        if self._sink is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="fw_logs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Drain what is queued, then let the thread finish."""
        thread, self._thread = self._thread, None
        if thread is not None:
            self._queue.put(_DONE)  # pyright: ignore[reportArgumentType]
            thread.join(timeout=JOIN_TIMEOUT)

    def _loop(self) -> None:
        """Take records one at a time, letting a bad sink hurt nothing but itself."""
        while True:
            record = self._queue.get()
            if record is _DONE:
                return
            try:
                self._sink(record)
            except Exception:
                self.dropped += 1


_DONE = object()


# ── One request at a time, and the reply that answers it ─────────────────────


class _Pending:
    """One request written to the wire, waiting for the reply that carries its id."""

    __slots__ = ("event", "payload", "status")

    def __init__(self) -> None:
        """Start unanswered, holding the event the worker will wait on."""
        self.event = threading.Event()
        self.status: int | None = None
        self.payload = b""


class _Job(NamedTuple):
    """One submitted request and the future that will carry its outcome."""

    future: "Future[bytes]"
    ns: int
    method: int
    payload: bytes
    timeout: float | None


class RequestBroker:
    """Writes one request at a time and settles each reply against its id."""

    def __init__(self, write: Callable[[bytes], Any], timeout: float) -> None:
        """Take the way to put bytes on the wire, and how long a reply may take."""
        self._write = write
        self._timeout = timeout
        self._jobs: queue.Queue[Any] = queue.Queue()
        self._pending: dict[int, _Pending] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self.unmatched = 0

    def start(self) -> None:
        """Start the one thread that writes and waits."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="fw_calls", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Refuse new work, fail what is queued, and let the thread finish."""
        self._closed.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            self._jobs.put(_DONE)
            thread.join(timeout=JOIN_TIMEOUT)
        with self._lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for pending in waiting:
            pending.event.set()
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            if job is not _DONE:
                job.future.set_exception(LinkClosed("the link closed"))

    def submit(
        self, ns: int, method: int, payload: bytes = b"", timeout: float | None = None
    ) -> "Future[bytes]":
        """Queue one request and return the future its reply will complete."""
        if self._closed.is_set():
            raise LinkClosed("the link is closed")
        future: Future[bytes] = Future()
        self._jobs.put(_Job(future, ns, method, payload, timeout))
        return future

    def request(
        self, ns: int, method: int, payload: bytes = b"", timeout: float | None = None
    ) -> bytes:
        """Queue one request and wait for the payload of the reply that answers it."""
        return self.submit(ns, method, payload, timeout).result()

    def settle(self, frame: fw_wire.Frame) -> None:
        """Match a reply to the request that is waiting for it, or count it lost."""
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

    def _loop(self) -> None:
        """Serve one job to completion before looking at the next."""
        while True:
            job = self._jobs.get()
            if job is _DONE:
                return
            if not job.future.set_running_or_notify_cancel():
                continue
            try:
                job.future.set_result(self._exchange(job))
            except BaseException as exc:  # noqa: BLE001
                job.future.set_exception(exc)

    def _exchange(self, job: Any) -> bytes:
        """Write one request and return the payload of the reply that answers it."""
        request_id, pending = self._reserve()
        try:
            self._write(
                fw_wire.encode(
                    fw_wire.seal_request(request_id, job.ns, job.method, job.payload)
                )
            )
            deadline = self._timeout if job.timeout is None else job.timeout
            if not pending.event.wait(deadline):
                raise LinkTimeout(
                    f"no reply to request {request_id} within {deadline}s"
                )
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

        if pending.status is None:
            raise LinkClosed("the link closed while the request was in flight")
        fw_api.raise_for_status(pending.status)
        return pending.payload


# ── The link itself ──────────────────────────────────────────────────────────


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
        """Open the port, or take a stream, and start serving calls either way."""
        self._namespaces: dict[str, fw_api.Namespace] = {}
        if (port is None) == (stream is None):
            raise LinkError("name a port or pass a stream, not both and not neither")
        if stream is None:
            import serial

            stream = serial.Serial(port, baudrate, timeout=READ_POLL)

        self._stream = stream
        self._logs = LogForwarder(on_log)
        self._broker = RequestBroker(stream.write, timeout)
        self._reader = FrameReader(stream, self._route)
        self._namespaces = fw_api.attach(self._invoke)

        self._logs.start()
        self._broker.start()
        self._reader.start()

    def __getattr__(self, name: str) -> fw_api.Namespace:
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

    @property
    def malformed(self) -> int:
        """Return how many runs arrived that were not frames."""
        return self._reader.malformed

    @property
    def unmatched(self) -> int:
        """Return how many replies arrived that nobody was waiting for."""
        return self._broker.unmatched

    @property
    def dropped(self) -> int:
        """Return how much was discarded: oversized runs, and logs nobody took."""
        return self._reader.dropped + self._logs.dropped

    def close(self) -> None:
        """Stop every thread, drop the port, and release anyone still waiting."""
        self._reader.stop()
        self._broker.stop()
        self._logs.stop()
        try:
            self._stream.close()
        except Exception:
            pass

    def _route(self, frame: fw_wire.Frame) -> None:
        """Send one frame to whichever collaborator it belongs to."""
        if frame.type == fw_api.RPC_FRAME_LOG:
            self._logs.offer(fw_wire.log_record(frame))
        elif frame.type == fw_api.RPC_FRAME_REP:
            self._broker.settle(frame)
        else:
            self._broker.unmatched += 1

    def _invoke(
        self, spec: fw_api.MethodSpec, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> Any:
        """Call a method by its spec, packing arguments and unpacking the reply."""
        kwargs = dict(kwargs)
        timeout = None
        if "timeout" not in spec.fields:
            timeout = kwargs.pop("timeout", None)

        payload = fw_api.arguments(spec, args, kwargs)
        reply = self._broker.request(spec.ns, spec.method, payload, timeout)
        return fw_api.result(spec, reply)


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
