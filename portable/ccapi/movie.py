from __future__ import annotations

import enum
from collections.abc import Generator
from contextlib import contextmanager

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.errors import InvalidStateError
from portable.ccapi.link import GET, POST, Link


class RecAction(enum.StrEnum):
    START = "start"
    STOP = "stop"


class MovieModeAction(enum.StrEnum):
    ON = "on"
    OFF = "off"


class Movie:
    def __init__(self, link: Link) -> None:
        self.link = link
        self._recording = False

    # ── The mode ─────────────────────────────────────────────────────────────

    def in_movie_mode(self) -> bool:
        body = self.link.json(GET, Endpoint.MOVIEMODE)
        return str(body.get("status", "")) == MovieModeAction.ON.value

    def enter_movie_mode(self) -> None:
        self._set_mode(MovieModeAction.ON)

    def leave_movie_mode(self) -> None:
        self._set_mode(MovieModeAction.OFF)

    @contextmanager
    def mode(self) -> Generator[None]:
        if self.in_movie_mode():
            yield
            return
        self.enter_movie_mode()
        try:
            yield
        finally:
            self.leave_movie_mode()

    def _set_mode(self, action: MovieModeAction) -> None:
        self.link.json(POST, Endpoint.MOVIEMODE, payload={"action": action.value})

    # ── The recording inside it ──────────────────────────────────────────────

    @property
    def recording_by_us(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        if not self.in_movie_mode():
            raise InvalidStateError(
                "movie mode is not on; nothing can be recorded from stills mode"
            )
        self._act(RecAction.START)
        self._recording = True

    def stop_recording(self) -> None:
        self._act(RecAction.STOP)
        self._recording = False

    @contextmanager
    def recording(self) -> Generator[None]:
        self.start_recording()
        try:
            yield
        finally:
            self.stop_recording()

    def _act(self, action: RecAction) -> None:
        self.link.json(POST, Endpoint.RECBUTTON, payload={"action": action.value})
