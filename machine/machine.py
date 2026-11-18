import importlib
import os
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from machine.activity import Activity
from shared import logs
from shared.subsystem import LinkState, Subsystem, truthy

ROSTER = ("transport", "capture", "detect")
DEMO = "demo"
DEMO_FLAG = "STEF_DEMO"

log = logs.as_component("machine")


def assembled(package_name: str) -> Subsystem:
    """Build the one instance of the subsystem a package exports as SUBSYSTEM."""
    module = importlib.import_module(package_name)
    made = getattr(module, "SUBSYSTEM", None)
    if made is None:
        raise ImportError(f"{package_name} exports no SUBSYSTEM")
    return made(module)


def default_roster() -> tuple[str, ...]:
    """Return the subsystems to assemble, with the demo board when STEF_DEMO is set."""
    return (*ROSTER, DEMO) if truthy(os.environ.get(DEMO_FLAG, "")) else ROSTER


class Busy(Exception):
    """Raised when the STEF machine is busy and cannot perform an activity."""

    def __init__(self, activity: Activity, holder: str) -> None:
        super().__init__(f"the machine is {activity.value}: {holder}")
        self.activity = activity
        self.holder = holder


class Machine:
    def __init__(self, roster: Sequence[str] | None = None) -> None:
        """A machine is a collection of subsystems, with a focus on one activity at a time."""
        self.roster = tuple(roster) if roster is not None else default_roster()
        self.subsystems: dict[str, Subsystem] = {}
        self._lock = threading.Lock()
        self._activity: Activity | None = None
        self._holder: str | None = None

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

    @property
    def focus_holder(self) -> str | None:
        """Return what holds the focus, such as "transport.raw.write", or None when idle."""
        return self._holder

    def focus_on(self, activity: Activity, holder: str) -> None:
        """Take the focus of the STEF machine for an activity, on behalf of holder."""
        with self._lock:
            if self._activity is not None:
                raise Busy(self._activity, self._holder or "")
            self._activity = activity
            self._holder = holder

    def unfocus(self) -> None:
        with self._lock:
            self._activity = None
            self._holder = None

    @contextmanager
    def focusing_on(self, activity: Activity, holder: str) -> Generator[None]:
        """Context manager for taking and freeing the focus of the STEF machine."""
        self.focus_on(activity, holder)
        try:
            yield
        finally:
            self.unfocus()


__all__ = [
    "DEMO",
    "DEMO_FLAG",
    "ROSTER",
    "Busy",
    "Machine",
    "assembled",
    "default_roster",
]
