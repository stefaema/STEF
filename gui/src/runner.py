"""One thing at a time on the hardware, and one stream telling you what happened.

A bench run is a blocking generator that holds the serial port: `verify_port`
waits on a boot, `flash_board` erases for tens of seconds. The server is async
and will happily start a second one while the first still owns the port, and two
writers on one port is a corrupted board rather than an error message.

So there is exactly one slot. Whoever holds it is what `StefState` reports, a
second attempt is refused with a sentence rather than queued, and the work runs
on a thread so the event loop stays free to stream what it produces.
"""

from __future__ import annotations

import asyncio
import itertools
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import Any

from shared.bench_api import Level
from shared.bench_api.stef import STEF, StefState

DEPTH = 512
BACKLOG = 200


class Busy(Exception):
    """Something already holds the machine, and it names what."""


@dataclass(frozen=True, slots=True)
class Record:
    """One line on the stream, whatever produced it."""

    seq: int
    time: float
    source: str
    level: str
    kind: str
    text: str
    data: Any = None

    def payload(self) -> dict[str, Any]:
        """Return the record as what crosses to the browser."""
        return {
            "seq": self.seq,
            "time": self.time,
            "source": self.source,
            "level": self.level,
            "kind": self.kind,
            "text": self.text,
            "data": self.data,
        }


class Stream:
    """Every listener's queue, and the backlog a late one catches up on."""

    def __init__(self) -> None:
        """Start with nobody listening and nothing said."""
        self._listeners: list[queue.Queue[Record]] = []
        self._backlog: list[Record] = []
        self._lock = threading.Lock()
        self._seq = itertools.count(1)

    def emit(self, record: Record) -> None:
        """Hand one record to every listener, dropping it for any that fell behind."""
        with self._lock:
            self._backlog.append(record)
            del self._backlog[:-BACKLOG]
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener.put_nowait(record)
            except queue.Full:
                pass

    def say(
        self, source: str, level: str, kind: str, text: str, data: Any = None
    ) -> None:
        """Emit one record, which is what every caller actually wants.

        Each carries a number that only goes up, so a listener that reconnects
        and is handed the backlog again can tell what it has already seen.
        """
        self.emit(Record(next(self._seq), time.time(), source, level, kind, text, data))

    def sink(self, source: str) -> Callable[[Any], None]:
        """Return a sink that puts a subsystem's own log records on this stream."""

        def take(record: Any) -> None:
            level = getattr(record, "level", Level.OK)
            self.say(
                source,
                getattr(level, "value", str(level)),
                "firmware",
                str(getattr(record, "text", record)),
            )

        return take

    def listen(self) -> tuple[queue.Queue[Record], list[Record]]:
        """Register a listener and hand back what it missed."""
        listener: queue.Queue[Record] = queue.Queue(maxsize=DEPTH)
        with self._lock:
            self._listeners.append(listener)
            return listener, list(self._backlog)

    def drop(self, listener: queue.Queue[Record]) -> None:
        """Forget a listener that has gone away."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)


class Slot:
    """The one thing the machine may be doing, and who is doing it."""

    def __init__(self, stream: Stream) -> None:
        """Start idle, holding the stream whatever runs will report on."""
        self.stream = stream
        self._lock = threading.Lock()
        self._holder: str | None = None

    @property
    def holder(self) -> str | None:
        """Return what holds the machine, or None while nothing does."""
        return self._holder

    def take(self, what: str) -> None:
        """Claim the machine, refusing rather than queueing when it is taken."""
        with self._lock:
            if self._holder is not None:
                raise Busy(f"{self._holder} is running")
            self._holder = what
            STEF.state = StefState.BENCHING

    def free(self) -> None:
        """Release the machine, whatever happened while it was held."""
        with self._lock:
            self._holder = None
            STEF.state = StefState.IDLE


async def stream_run(
    slot: Slot, what: str, produce: Callable[[], Iterator[Any]]
) -> AsyncIterator[Any]:
    """Run a blocking generator on a thread, yielding what it produces as it goes.

    The generator is the contract's own `run()`, which yields one outcome per
    step as the step settles. Pulling it on a thread and handing each item to the
    loop is what keeps "the screen fills in step by step" true across a socket.
    """
    loop = asyncio.get_running_loop()
    handoff: asyncio.Queue[Any] = asyncio.Queue()
    done = object()

    def pump() -> None:
        try:
            for item in produce():
                loop.call_soon_threadsafe(handoff.put_nowait, item)
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(
                handoff.put_nowait, {"error": f"{type(exc).__name__}: {exc}"}
            )
        finally:
            loop.call_soon_threadsafe(handoff.put_nowait, done)

    slot.take(what)
    threading.Thread(target=pump, name=f"bench:{what}", daemon=True).start()
    try:
        while True:
            item = await handoff.get()
            if item is done:
                return
            yield item
    finally:
        slot.free()


async def call_off_loop(slot: Slot, what: str, work: Callable[[], Any]) -> Any:
    """Run one blocking call on a thread, holding the slot for as long as it takes."""
    slot.take(what)
    try:
        return await asyncio.to_thread(work)
    finally:
        slot.free()
