from __future__ import annotations

import enum
import logging
import time
from collections.abc import Generator
from contextlib import contextmanager

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.errors import InvalidStateError
from portable.ccapi.link import GET, POST, Link

SETTLE = 3.0
POLL = 0.1

log = logging.getLogger("ccapi.movie")


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
        self._change_mode(MovieModeAction.ON)

    def leave_movie_mode(self) -> None:
        self._change_mode(MovieModeAction.OFF)

    @contextmanager
    def mode(self) -> Generator[None]:
        if self.in_movie_mode():
            log.debug("already in movie mode; leaving it on at exit")
            yield
            return
        self.enter_movie_mode()
        try:
            yield
        finally:
            self.leave_movie_mode()

    def _change_mode(self, action: MovieModeAction) -> None:
        """Ask for a mode and return once the camera is in it.

        The 200 acknowledges the request; the mirror and the sensor take longer
        than the next call does to arrive. A single read afterwards is a race,
        and losing it looks exactly like the camera refusing.
        """
        self.link.json(POST, Endpoint.MOVIEMODE, payload={"action": action.value})
        wanted = action is MovieModeAction.ON
        if not self._mode_becomes(wanted, SETTLE):
            raise InvalidStateError(
                f"the camera took movie mode {action.value} but is not there "
                f"after {SETTLE:.0f} s"
            )

    def _mode_becomes(self, wanted: bool, timeout: float) -> bool:
        """Whether the mode reads as wanted before the time runs out."""
        deadline = time.monotonic() + timeout
        while True:
            if self.in_movie_mode() is wanted:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL)

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
