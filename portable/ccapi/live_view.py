from __future__ import annotations

import enum
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.framing import Unpacker
from portable.ccapi.link import GET, POST, Link
from portable.ccapi.vocabulary import Packet, PacketKind

OFF = "off"


class ViewSize(enum.StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class CameraDisplay(enum.StrEnum):
    ON = "on"
    OFF = "off"
    KEEP = "keep"


class Stream:
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

    def running(self) -> bool:
        return self._size != OFF

    def frame(self) -> bytes:
        return self.link.blob(Endpoint.LIVEVIEW_FLIP)

    def start(
        self,
        size: ViewSize = ViewSize.MEDIUM,
        display: CameraDisplay = CameraDisplay.KEEP,
    ) -> Stream:
        self.link.json(
            POST,
            Endpoint.LIVEVIEW,
            payload={
                "liveviewsize": size.value,
                "cameradisplay": display.value,
            },
        )
        self._size = size.value
        return Stream(self.link.chunks(Endpoint.LIVEVIEW_SCROLLDETAIL))

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
        found = self.running()
        stream = self.start(size, display)
        try:
            yield stream
        finally:
            if not found:
                self.stop()

    def angle(self) -> dict[str, object]:
        return self.link.json(GET, Endpoint.LIVEVIEW_ANGLEINFORMATION)
