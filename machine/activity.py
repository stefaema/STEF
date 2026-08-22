import enum
import threading
from collections.abc import Generator
from contextlib import contextmanager


class Activity(enum.Enum):
    IDLE = "idle"
    BENCHING = "benching"
    SCANNING = "scanning"
    CONFIGURING = "configuring"


AREAS: dict[str, Activity] = {
    "bench": Activity.BENCHING,
    "scan": Activity.SCANNING,
    "config": Activity.CONFIGURING,
}


class Busy(Exception):
    pass


class Focus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._activity = Activity.IDLE
        self._by: str | None = None
        self._refusal = ""

    @property
    def activity(self) -> Activity:
        return self._activity

    @property
    def by(self) -> str | None:
        return self._by

    @property
    def refusal(self) -> str:
        return self._refusal

    def take(self, activity: Activity, by: str, refusal: str) -> None:
        with self._lock:
            if self._by is not None:
                raise Busy(self._refusal)
            self._activity = activity
            self._by = by
            self._refusal = refusal

    def free(self) -> None:
        with self._lock:
            self._activity = Activity.IDLE
            self._by = None
            self._refusal = ""

    @contextmanager
    def doing(self, activity: Activity, by: str, refusal: str) -> Generator[None]:
        self.take(activity, by, refusal)
        try:
            yield
        finally:
            self.free()

    def blocked_reason(self, area: str) -> str | None:
        if self._activity is Activity.IDLE or AREAS[area] is self._activity:
            return None
        return self._refusal


__all__ = ["AREAS", "Activity", "Busy", "Focus"]
