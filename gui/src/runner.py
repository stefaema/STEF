"""One thing at a time on the hardware, and one stream telling you what happened.

A bench run is a blocking generator that holds the serial port: `verify_port`
waits on a boot, `flash_board` erases for tens of seconds. The server is async
and will happily start a second one while the first still owns the port, and two
writers on one port is a corrupted board rather than an error message.

So the machine is held for the length of one run. Whoever holds it is what the
machine reports it is doing, a second attempt is refused with a sentence rather
than queued, and the work runs on a thread so the event loop stays free to
stream what it produces.
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

from machine import Activity, Machine
from shared.bench_api import Level

DEPTH = 512
BACKLOG = 200

# What a logged level is called on a screen, which has three weights and not six.
LEVELS = {
    "TRACE": Level.OK,
    "DEBUG": Level.OK,
    "INFO": Level.OK,
    "SUCCESS": Level.OK,
    "WARNING": Level.WARN,
    "ERROR": Level.ERROR,
    "CRITICAL": Level.ERROR,
}


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

    def sink(self, message: Any) -> None:
        """Put one logged line on this stream, as `shared.logs` hands it to a sink.

        The component is read off the record rather than off the rendered line,
        so a format change is a format change and nothing more.
        """
        record = getattr(message, "record", None)
        if record is None:
            self.say("stef", Level.OK.value, "log", str(message).rstrip())
            return
        self.say(
            str(record["extra"].get("component", "stef")),
            LEVELS.get(record["level"].name, Level.OK).value,
            "log",
            str(record["message"]),
        )

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


async def stream_run(
    stef: Machine,
    activity: Activity,
    what: str,
    refusal: str,
    produce: Callable[[], Iterator[Any]],
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

    stef.take(activity, what, refusal)
    threading.Thread(target=pump, name=f"bench:{what}", daemon=True).start()
    try:
        while True:
            item = await handoff.get()
            if item is done:
                return
            yield item
    finally:
        stef.free()


async def call_off_loop(
    stef: Machine, activity: Activity, what: str, refusal: str, work: Callable[[], Any]
) -> Any:
    """Run one blocking call on a thread, holding the machine for as long as it takes."""
    stef.take(activity, what, refusal)
    try:
        return await asyncio.to_thread(work)
    finally:
        stef.free()
