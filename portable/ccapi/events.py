"""Camera state changes from polling or the push stream."""

from __future__ import annotations

import json as jsonlib
import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.errors import ALREADY_STARTED, DeviceError, InvalidStateError
from portable.ccapi.framing import Unpacker
from portable.ccapi.link import DELETE, GET, Link
from portable.ccapi.vocabulary import (
    CameraState,
    PacketKind,
    PollWait,
    StateChange,
    state_change,
)

log = logging.getLogger("ccapi.events")


class Feed:
    """Iterator of state changes from the push event stream."""

    def __init__(self, link: Link, chunks: Iterator[bytes]) -> None:
        self.link = link
        self._chunks = chunks
        self._unpacker = Unpacker()
        self._state = CameraState()

    @property
    def latest(self) -> CameraState:
        return self._state

    def __iter__(self) -> Iterator[StateChange]:
        for chunk in self._chunks:
            for packet in self._unpacker.feed(chunk):
                if packet.kind is not PacketKind.EVENT:
                    continue
                change = self._read(packet.body)
                if change is None or change.empty:
                    continue
                self._state = self._state.merged(change)
                yield change

    @staticmethod
    def _read(body: bytes) -> StateChange | None:
        try:
            loaded = jsonlib.loads(body)
        except ValueError:
            return None
        return state_change(loaded) if isinstance(loaded, dict) else None


class Events:
    def __init__(self, link: Link) -> None:
        self.link = link
        self._watching = False

    @property
    def watched_by_us(self) -> bool:
        return self._watching

    def poll(self, wait: PollWait = PollWait.IMMEDIATELY) -> StateChange:
        return state_change(
            self.link.json(GET, Endpoint.POLLING, query={"timeout": wait.value})
        )

    def stop_polling(self) -> None:
        self.link.json(DELETE, Endpoint.POLLING)

    def start_watching(self) -> Feed:
        chunks = self._open_stream()
        self._watching = True
        return Feed(self.link, chunks)

    def _open_stream(self) -> Iterator[bytes]:
        """Open the monitoring stream, clearing a stale one from an earlier run."""
        try:
            return self.link.chunks(Endpoint.MONITORING)
        except InvalidStateError as exc:
            if ALREADY_STARTED not in str(exc) or self.watched_by_us:
                raise
            log.warning("a monitoring stream outlived its process; restarting it")
            self.stop_watching()
            return self.link.chunks(Endpoint.MONITORING)

    def stop_watching(self) -> None:
        try:
            self.link.json(DELETE, Endpoint.MONITORING)
        except DeviceError as exc:
            log.debug("nothing to stop watching: %s", exc)
        self._watching = False

    @contextmanager
    def watching(self) -> Generator[Feed]:
        feed = self.start_watching()
        try:
            yield feed
        finally:
            self.stop_watching()
