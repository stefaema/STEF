import importlib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

from machine.activity import AREAS, Activity, Focus
from machine.subsystem import Subsystem
from shared import bench_api, config, logs
from shared.subsystem import SubsystemSpec, SubsystemState

ROSTER = ("transport", "capture", "detect")

log = logs.component("machine")


def assembled(package: str) -> Subsystem[None]:
    module = importlib.import_module(package)
    spec = SubsystemSpec.of(module)
    return Subsystem(
        spec=spec,
        config=config.derive(spec),
        bench=bench_api.derive(spec),
        scan=None,
        module=module,
    )


class Machine:
    def __init__(self, roster: Sequence[str] = ROSTER) -> None:
        self.roster = tuple(roster)
        self.subsystems: dict[str, Subsystem[Any]] = {}
        self._focus = Focus()

    def assemble(self) -> None:
        for name in self.roster:
            if name in self.subsystems:
                continue
            try:
                self.subsystems[name] = assembled(name)
            except (ImportError, KeyError) as exc:
                log.debug("no subsystem {}: {}", name, exc)

    def subsystem(self, name: str) -> Subsystem[Any]:
        return self.subsystems[name]

    def state_of(self, name: str) -> SubsystemState:
        found = self.subsystems.get(name)
        return found.state if found is not None else SubsystemState.DOWN

    @property
    def activity(self) -> Activity:
        return self._focus.activity

    @property
    def busy_with(self) -> str | None:
        return self._focus.by

    def take(self, activity: Activity, by: str, refusal: str) -> None:
        self._focus.take(activity, by, refusal)

    def free(self) -> None:
        self._focus.free()

    @contextmanager
    def doing(self, activity: Activity, by: str, refusal: str) -> Generator[None]:
        with self._focus.doing(activity, by, refusal):
            yield

    def blocked_reason(self, area: str) -> str | None:
        return self._focus.blocked_reason(area)

    def may_open(self, area: str) -> bool:
        return self._focus.blocked_reason(area) is None

    def openings(self) -> dict[str, str | None]:
        return {area: self._focus.blocked_reason(area) for area in AREAS}


__all__ = ["ROSTER", "Machine", "assembled"]
