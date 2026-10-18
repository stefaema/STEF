import enum
import threading
from types import ModuleType
from typing import Any, ClassVar

from shared.config import SubsystemConfig
from shared.subsystem.prose import prose_of
from shared.subsystem.records import Input, Readiness, Result, answered


class LinkState(enum.Enum):
    """Whether one subsystem is reachable."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


class NotLinked(Exception):
    pass


class NotReady(Exception):
    pass


class Subsystem:
    safe_state: ClassVar[str] = ""

    def __init__(self, package: ModuleType) -> None:
        self.package = package.__name__
        self.id = self.package.rpartition(".")[2]
        self.summary, self.description = prose_of(package)
        self.config = SubsystemConfig(package=self.package)

    def link_state(self) -> LinkState:
        return LinkState.DOWN

    def link_reason(self) -> str | None:
        return None

    def stop(self) -> None:
        pass

    def cancel(self) -> None:
        pass

    def facts(self) -> Result | None:
        return None

    def owns(self, module_name: str) -> bool:
        return module_name == self.package or module_name.startswith(f"{self.package}.")


LOST = "the connection stopped answering"


class Linked[Target](Subsystem):
    target: ClassVar[Input]

    def __init__(self, package: ModuleType) -> None:
        super().__init__(package)
        self._link_lock = threading.Lock()
        self._handle: Any = None
        self._linking = False
        self._failure: str | None = None

    def probe(self, target: Target) -> Readiness | None:
        return None

    def _open(self, target: Target) -> Any:
        raise NotImplementedError

    def _close(self, handle: Any) -> None:
        raise NotImplementedError

    def _alive(self, handle: Any) -> bool:
        return True

    def link_state(self) -> LinkState:
        with self._link_lock:
            if self._linking:
                return LinkState.LINKING
            if self._handle is not None:
                return LinkState.UP if self._alive(self._handle) else LinkState.ERROR
            return LinkState.ERROR if self._failure else LinkState.DOWN

    def link_reason(self) -> str | None:
        with self._link_lock:
            if self._handle is not None and not self._alive(self._handle):
                return LOST
            return self._failure

    def handle(self) -> Any:
        with self._link_lock:
            found = self._handle
        if found is None:
            raise NotLinked(f"{self.id} is not connected")
        return found

    def connect(self, target: Target) -> None:
        with self._link_lock:
            if self._linking:
                raise NotReady("already connecting")
            if self._handle is not None and self._alive(self._handle):
                raise NotReady("already connected")
            stale, self._handle = self._handle, None
            self._linking = True
            self._failure = None
        if stale is not None:
            self._close_quietly(stale)
        try:
            verdict = answered(self.probe(target))
            if not verdict:
                raise NotReady(verdict.reason)
            opened = self._open(target)
        except NotReady:
            with self._link_lock:
                self._linking = False
            raise
        except Exception as exc:
            with self._link_lock:
                self._linking = False
                self._failure = f"{type(exc).__name__}: {exc}"
            raise
        with self._link_lock:
            self._handle = opened
            self._linking = False

    def disconnect(self) -> None:
        errors: list[Exception] = []
        for action in (self.cancel, self._stop_if_up):
            try:
                action()
            except Exception as exc:
                errors.append(exc)
        with self._link_lock:
            closing, self._handle = self._handle, None
            self._failure = None
        if closing is not None:
            try:
                self._close(closing)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def _stop_if_up(self) -> None:
        if self.link_state() is LinkState.UP:
            self.stop()

    def _close_quietly(self, handle: Any) -> None:
        try:
            self._close(handle)
        except Exception:
            pass
