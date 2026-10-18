import importlib
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from machine.activity import Activity
from shared import logs
from shared.subsystem import LinkState, Subsystem

ROSTER = ("transport", "capture", "detect")

log = logs.as_component("machine")


def assembled(package_name: str) -> Subsystem:
    """Build the one instance of the subsystem a package exports as SUBSYSTEM."""
    module = importlib.import_module(package_name)
    made = getattr(module, "SUBSYSTEM", None)
    if made is None:
        raise ImportError(f"{package_name} exports no SUBSYSTEM")
    return made(module)


class Busy(Exception):
    """Raised when the STEF machine is busy and cannot perform an activity."""

    def __init__(self, activity: Activity) -> None:
        super().__init__(f"the machine is {activity.value}")
        self.activity = activity


class Machine:
    def __init__(self, roster: Sequence[str] = ROSTER) -> None:
        """A machine is a collection of subsystems, with a focus on one activity at a time."""
        self.roster = tuple(roster)
        self.subsystems: dict[str, Subsystem] = {}
        self._lock = threading.Lock()
        self._activity: Activity | None = None

    def assemble(self) -> None:
        """Load all subsystems in the roster, skipping any that cannot be loaded."""
        for name in self.roster:
            if name in self.subsystems:
                continue
            try:
                self.subsystems[name] = assembled(name)
            except (ImportError, KeyError, OSError) as exc:
                log.debug("no subsystem {}: {}", name, exc)

    def subsystem(self, name: str) -> Subsystem:
        """Return the subsystem with the given name, or raise KeyError if not found."""
        return self.subsystems[name]

    def link_state_of(self, name: str) -> LinkState:
        """Return the link state of the subsystem with the given name, or DOWN if not found."""
        found = self.subsystems.get(name)
        return found.link_state() if found is not None else LinkState.DOWN

    @property
    def activity(self) -> Activity | None:
        return self._activity

    def focus_on(self, activity: Activity) -> None:
        """Take the focus of the STEF machine for a given activity."""
        with self._lock:
            if self._activity is not None:
                raise Busy(self._activity)
            self._activity = activity

    def unfocus(self) -> None:
        with self._lock:
            self._activity = None

    @contextmanager
    def focusing_on(self, activity: Activity) -> Generator[None]:
        """Context manager for taking and freeing the focus of the STEF machine."""
        self.focus_on(activity)
        try:
            yield
        finally:
            self.unfocus()


__all__ = ["ROSTER", "Busy", "Machine", "assembled"]
