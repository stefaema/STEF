"""Live view streaming."""

from __future__ import annotations

import enum
import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.errors import ALREADY_STARTED, InvalidStateError
from portable.ccapi.framing import Unpacker
from portable.ccapi.link import GET, POST, Link
from portable.ccapi.vocabulary import Packet, PacketKind

OFF = "off"

log = logging.getLogger("ccapi.live_view")


class ViewSize(enum.StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class CameraDisplay(enum.StrEnum):
    ON = "on"
    OFF = "off"
    KEEP = "keep"


class Stream:
    """Iterator of packets from the live view stream."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._unpacker = Unpacker()

    def __iter__(self) -> Iterator[Packet]:
        for chunk in self._chunks:
            yield from self._unpacker.feed(chunk)

    def frames(self) -> Iterator[bytes]:
        for packet in self:
            if packet.kind is PacketKind.IMAGE:
                yield packet.body


class LiveView:
    def __init__(self, link: Link) -> None:
        self.link = link
        self._size: str = OFF

    @property
    def started_by_us(self) -> bool:
        return self._size != OFF

    def frame(self) -> bytes:
        return self.link.blob(Endpoint.LIVEVIEW_FLIP)

    def start(
        self,
        size: ViewSize = ViewSize.MEDIUM,
        display: CameraDisplay = CameraDisplay.KEEP,
    ) -> Stream:
        chunks = self._open_stream(size, display)
        self._size = size.value
        return Stream(chunks)

    def _open_stream(self, size: ViewSize, display: CameraDisplay) -> Iterator[bytes]:
        """Open the live view stream, clearing a stale one from an earlier run."""
        self._configure(size, display)
        try:
            return self.link.chunks(Endpoint.LIVEVIEW_SCROLLDETAIL)
        except InvalidStateError as exc:
            if ALREADY_STARTED not in str(exc) or self.started_by_us:
                raise
            log.warning("a live view stream outlived its process; restarting it")
            self.stop()
            self._configure(size, display)
            return self.link.chunks(Endpoint.LIVEVIEW_SCROLLDETAIL)

    def _configure(self, size: ViewSize, display: CameraDisplay) -> None:
        self.link.json(
            POST,
            Endpoint.LIVEVIEW,
            payload={
                "liveviewsize": size.value,
                "cameradisplay": display.value,
            },
        )

    def stop(self) -> None:
        self.link.json(
            POST,
            Endpoint.LIVEVIEW,
            payload={
                "liveviewsize": OFF,
                "cameradisplay": CameraDisplay.KEEP.value,
            },
        )
        self._size = OFF

    @contextmanager
    def session(
        self,
        size: ViewSize = ViewSize.MEDIUM,
        display: CameraDisplay = CameraDisplay.KEEP,
    ) -> Generator[Stream]:
        ours = not self.started_by_us
        if not ours:
            log.debug("we started live view already; leaving it up on exit")
        stream = self.start(size, display)
        try:
            yield stream
        finally:
            if ours:
                self.stop()

    def angle(self) -> dict[str, object]:
        return self.link.json(GET, Endpoint.LIVEVIEW_ANGLEINFORMATION)
