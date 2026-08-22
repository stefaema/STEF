"""Camera client: the link plus every controller."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from portable.ccapi.config import CameraConfig
from portable.ccapi.endpoints import Endpoint
from portable.ccapi.errors import CcapiError
from portable.ccapi.events import Events
from portable.ccapi.filesystem import Filesystem
from portable.ccapi.functions import Functions
from portable.ccapi.link import Link, Transport
from portable.ccapi.live_view import LiveView
from portable.ccapi.movie import Movie
from portable.ccapi.settings import Setting, Settings
from portable.ccapi.shooting import Shooting
from portable.ccapi.status import Status
from portable.ccapi.vocabulary import ContentKind, LinkState, PollWait

log = logging.getLogger("ccapi.camera")

NAMED = {str(one) for one in Endpoint} | {str(one) for one in Setting}


class Camera:
    def __init__(
        self, config: CameraConfig, transport: Transport | None = None
    ) -> None:
        self.link = Link(config, transport)
        self.status = Status(self.link)
        self.settings = Settings(self.link)
        self.functions = Functions(self.link)
        self.filesystem = Filesystem(self.link)
        self.events = Events(self.link)
        self.shooting = Shooting(self.link)
        self.movie = Movie(self.link)
        self.live_view = LiveView(self.link)

    @property
    def config(self) -> CameraConfig:
        return self.link.config

    def connect(self) -> None:
        self.link.connect()
        unnamed = self.link.registry.unnamed(NAMED)
        if unnamed:
            log.info(
                "%d endpoints this build has no name for: %s",
                len(unnamed),
                ", ".join(unnamed),
            )

    def disconnect(self) -> None:
        self._stop_what_we_started()
        self.link.disconnect()

    def _stop_what_we_started(self) -> None:
        """Stop the recording and streams this session started, ignoring refusals."""
        if not self.link.up:
            return
        for what, ours, stop in (
            ("recording", self.movie.recording_by_us, self.movie.stop_recording),
            ("live view", self.live_view.started_by_us, self.live_view.stop),
            ("monitoring", self.events.watched_by_us, self.events.stop_watching),
        ):
            if not ours:
                continue
            try:
                stop()
            except CcapiError as exc:
                log.warning("could not stop %s before disconnecting: %s", what, exc)

    @contextmanager
    def connection(self) -> Generator[None]:
        ours = self.link.state is not LinkState.UP
        if ours:
            self.connect()
        try:
            yield
        finally:
            if ours:
                self.disconnect()

    def __enter__(self) -> Camera:
        self.connect()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.disconnect()

    def capture_confirmed(
        self,
        af: bool = False,
        timeout: float = 10.0,
        wait: PollWait = PollWait.SHORT,
    ) -> tuple[str, ...]:
        self.events.poll(PollWait.IMMEDIATELY)
        self.shooting.capture(af=af)
        deadline = time.monotonic() + timeout
        landed: list[str] = []
        while time.monotonic() < deadline:
            change = self.events.poll(wait)
            landed.extend(change.added)
            if landed:
                return tuple(landed)
        return ()

    def landed_since(self, baseline: int) -> int:
        return self.filesystem.file_count - baseline

    def download(
        self,
        paths: Iterable[str],
        into: Path,
        kind: ContentKind = ContentKind.MAIN,
        discard: bool = False,
    ) -> tuple[Path, ...]:
        into.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for path in paths:
            target = into / path.rsplit("/", 1)[-1]
            target.write_bytes(self.filesystem.fetch(path, kind))
            written.append(target)
            if discard:
                self.filesystem.discard(path)
        return tuple(written)
