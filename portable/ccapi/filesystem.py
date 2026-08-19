from __future__ import annotations

from collections.abc import Iterator

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.link import DELETE, GET, Link
from portable.ccapi.vocabulary import (
    ContentKind,
    FileInfo,
    FileType,
    Storage,
    file_info,
    storage,
    storage_list,
)

LIST = "list"
NUMBER = "number"


class Filesystem:
    def __init__(self, link: Link) -> None:
        self.link = link

    # ── The media it is made of ──────────────────────────────────────────────

    def storages(self) -> tuple[Storage, ...]:
        return storage_list(self.link.json(GET, Endpoint.STORAGE))

    def current(self) -> Storage:
        return storage(self.link.json(GET, Endpoint.CURRENTSTORAGE))

    def current_directory(self) -> str:
        body = self.link.json(GET, Endpoint.CURRENTDIRECTORY)
        return str(body.get("path", ""))

    @property
    def capacity(self) -> int:
        return self.current().capacity

    @property
    def free(self) -> int:
        return self.current().free

    @property
    def file_count(self) -> int:
        return self.current().file_count

    def holds(self, frames: int, bytes_each: int) -> bool:
        return self.current().holds(frames, bytes_each)

    # ── Walking it ───────────────────────────────────────────────────────────

    def volumes(self) -> tuple[str, ...]:
        body = self.link.json(GET, Endpoint.CONTENTS)
        return tuple(str(entry) for entry in body.get("path", ()))

    def directories(self, volume: str) -> tuple[str, ...]:
        body = self.link.json(GET, Endpoint.CONTENTS, volume)
        return tuple(str(entry) for entry in body.get("path", ()))

    def under(
        self,
        directory: str,
        kind: FileType = FileType.ALL,
        page: int | None = None,
    ) -> tuple[str, ...]:
        query = {"kind": LIST, "type": kind.value}
        if page is not None:
            query["page"] = str(page)
        body = self.link.json(GET, Endpoint.CONTENTS, directory, query=query)
        return tuple(str(entry) for entry in body.get("path", ()))

    def count(self, directory: str, kind: FileType = FileType.ALL) -> int:
        body = self.link.json(
            GET,
            Endpoint.CONTENTS,
            directory,
            query={"kind": NUMBER, "type": kind.value},
        )
        return int(body.get("contentsnumber") or 0)

    def walk(self, directory: str, kind: FileType = FileType.ALL) -> Iterator[str]:
        page = 1
        while True:
            found = self.under(directory, kind, page=page)
            if not found:
                return
            yield from found
            page += 1

    # ── Taking things off it ─────────────────────────────────────────────────

    def fetch(
        self,
        path: str,
        kind: ContentKind = ContentKind.MAIN,
        byte_range: tuple[int, int] | None = None,
    ) -> bytes:
        return self.link.blob(
            Endpoint.CONTENTS,
            _relative(path),
            query={"kind": kind.value},
            byte_range=byte_range,
        )

    def info(self, path: str) -> FileInfo:
        body = self.link.json(
            GET, Endpoint.CONTENTS, _relative(path), query={"kind": "info"}
        )
        return file_info(path, body)

    def discard(self, path: str) -> None:
        self.link.json(DELETE, Endpoint.CONTENTS, _relative(path))

    def discard_directory(self, directory: str) -> None:
        self.link.json(DELETE, Endpoint.CONTENTS, _relative(directory))


def _relative(path: str) -> str:
    marker = "/contents/"
    at = path.find(marker)
    return path[at + len(marker) :] if at >= 0 else path.lstrip("/")
