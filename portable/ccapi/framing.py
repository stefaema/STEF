from __future__ import annotations

from collections.abc import Iterable, Iterator

from portable.ccapi.vocabulary import Packet, PacketKind

START = b"\xff\x00"
END = b"\xff\xff"
HEADER = 7
FOOTER = 2


class Unpacker:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._dropped = 0

    @property
    def pending(self) -> int:
        return len(self._buffer)

    @property
    def dropped(self) -> int:
        return self._dropped

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, chunk: bytes) -> Iterator[Packet]:
        if chunk:
            self._buffer.extend(chunk)
        while True:
            found = self._align()
            if not found:
                return
            if len(self._buffer) < HEADER:
                return
            size = int.from_bytes(self._buffer[3:HEADER], "big")
            whole = HEADER + size + FOOTER
            if len(self._buffer) < whole:
                return
            if bytes(self._buffer[whole - FOOTER : whole]) != END:
                self._resync()
                continue
            body = bytes(self._buffer[HEADER : HEADER + size])
            kind = self._kind(self._buffer[2])
            del self._buffer[:whole]
            if kind is not None:
                yield Packet(kind=kind, body=body)

    def _align(self) -> bool:
        at = self._buffer.find(START)
        if at == 0:
            return True
        if at > 0:
            self._dropped += at
            del self._buffer[:at]
            return True
        keep = 1 if self._buffer and self._buffer[-1] == 0xFF else 0
        self._dropped += len(self._buffer) - keep
        del self._buffer[: len(self._buffer) - keep]
        return False

    def _resync(self) -> None:
        self._dropped += len(START)
        del self._buffer[: len(START)]

    @staticmethod
    def _kind(raw: int) -> PacketKind | None:
        try:
            return PacketKind(raw)
        except ValueError:
            return None


def unpack(chunks: Iterable[bytes]) -> Iterator[Packet]:
    unpacker = Unpacker()
    for chunk in chunks:
        yield from unpacker.feed(chunk)


def pack(packet: Packet) -> bytes:
    return b"".join(
        (
            START,
            bytes((packet.kind.value,)),
            len(packet.body).to_bytes(4, "big"),
            packet.body,
            END,
        )
    )
