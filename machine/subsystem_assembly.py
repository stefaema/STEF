from dataclasses import dataclass
from types import ModuleType
from typing import Any, Generic, TypeVar

from shared import bench_api
from shared.bench_api import SubsystemBench
from shared.config import SubsystemConfig
from shared.subsystem import SubsystemLinkState, SubsystemSpec, link_state_of

# Scan doesn't exist yet
Scan = TypeVar("Scan")


@dataclass(frozen=True)
class Subsystem(Generic[Scan]):
    spec: SubsystemSpec
    config: SubsystemConfig
    bench: SubsystemBench
    scan: Scan
    module: ModuleType

    @property
    def link_state(self) -> SubsystemLinkState:
        return link_state_of(self.module)


def subsystem_json(item: "Subsystem[Any]") -> dict[str, Any]:
    link_state = item.link_state
    return {
        "id": item.spec.id,
        "summary": item.spec.summary,
        "description": item.spec.description,
        "link": link_state.value,
        "routines": [
            bench_api.routine_json(one, link_state)
            for one in item.bench.routines.values()
        ],
    }


__all__ = ["Subsystem", "subsystem_json"]
