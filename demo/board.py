import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

HEALTHY = "healthy"
REFUSES = "refuses"
FAILS_TO_OPEN = "fails to open"
DIES = "dies after a while"

TARGETS = (HEALTHY, REFUSES, FAILS_TO_OPEN, DIES)

DIES_AFTER_S = 10.0


@dataclass
class Drive:
    enabled: bool = False
    velocity: int = 0
    jammed: bool = False


class Board:
    def __init__(
        self,
        dies_after: float | None = None,
        on_death: Callable[[], None] | None = None,
    ) -> None:
        """Stops answering after dies_after seconds and calls on_death at that time."""
        self.opened = time.monotonic()
        self.dies_after = dies_after
        self.drives = {"left": Drive(), "right": Drive()}
        self.closed = False
        self._death_timer: threading.Timer | None = None
        if dies_after is not None and on_death is not None:
            self._death_timer = threading.Timer(dies_after, on_death)
            self._death_timer.daemon = True
            self._death_timer.start()

    @property
    def alive(self) -> bool:
        if self.closed:
            return False
        if self.dies_after is None:
            return True
        return time.monotonic() - self.opened < self.dies_after

    def answering(self) -> Board:
        if not self.alive:
            raise ConnectionError("the demo board stopped answering")
        return self

    def drive(self, name: str) -> Drive:
        found = self.answering().drives.get(name)
        if found is None:
            raise KeyError(f"the demo board has no drive {name!r}")
        return found

    def temperature(self) -> float:
        self.answering()
        moving = sum(abs(one.velocity) for one in self.drives.values())
        return round(24.0 + moving / 1000, 1)

    def close(self) -> None:
        self.closed = True
        if self._death_timer is not None:
            self._death_timer.cancel()
