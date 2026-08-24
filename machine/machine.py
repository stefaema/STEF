import importlib
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

from machine.activity import Activity
from machine.subsystem_assembly import Subsystem
from shared import bench_api, config, logs
from shared.subsystem import SubsystemLinkState, SubsystemSpec

ROSTER = ("transport", "capture", "detect")

log = logs.as_component("machine")


def assembled(package_name: str) -> Subsystem[None]:
    """Assemble a subsystem from a package name."""
    module = importlib.import_module(package_name)
    spec = SubsystemSpec.of(module)
    return Subsystem(
        spec=spec,
        config=config.derive(spec),
        bench=bench_api.derive(spec),
        scan=None,
        module=module,
    )


class Busy(Exception):
    """Raised when the STEF machine is busy and cannot perform an activity."""

    def __init__(self, activity: Activity) -> None:
        super().__init__(f"the machine is {activity.value}")
        self.activity = activity


class Machine:
    def __init__(self, roster: Sequence[str] = ROSTER) -> None:
        """A machine is a collection of subsystems, with a focus on one activity at a time."""
        self.roster = tuple(roster)
        self.subsystems: dict[str, Subsystem[Any]] = {}
        self._lock = threading.Lock()
        self._activity: Activity | None = None

    def assemble(self) -> None:
        """Load all subsystems in the roster, skipping any that cannot be loaded."""
        for name in self.roster:
            if name in self.subsystems:
                continue
            try:
                self.subsystems[name] = assembled(name)
            except (ImportError, KeyError) as exc:
                log.debug("no subsystem {}: {}", name, exc)

    def subsystem(self, name: str) -> Subsystem[Any]:
        """Return the subsystem with the given name, or raise KeyError if not found."""
        return self.subsystems[name]

    def link_state_of(self, name: str) -> SubsystemLinkState:
        """Return the link state of the subsystem with the given name, or DOWN if not found."""
        found = self.subsystems.get(name)
        return found.link_state if found is not None else SubsystemLinkState.DOWN

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
