from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from shared.bench_api import PASSED, Routine, StepOutcome, StepStatus, verdict

IDLE = "idle"
RUNNING = "running"


def address_of(subsystem: str, key: str) -> str:
    return f"{subsystem}.{key}"


def key_of(item: Routine) -> str:
    return f"{item.group}.{item.name}"


@dataclass
class RunState:
    address: str
    status: str = IDLE
    when: float | None = None
    values: dict = field(default_factory=dict)
    outcomes: list[StepOutcome] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return bool(self.outcomes) or self.status == RUNNING

    @property
    def running(self) -> bool:
        return self.status == RUNNING

    def settled_at(self, index: int) -> StepOutcome | None:
        return self.outcomes[index] if index < len(self.outcomes) else None


class RunStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, RunState] = {}

    def begin(self, address: str, values: dict) -> RunState:
        with self._lock:
            started = RunState(address, RUNNING, time.time(), dict(values), [])
            self._held[address] = started
            return started

    def record(self, address: str, outcome: StepOutcome) -> None:
        with self._lock:
            found = self._held.get(address)
            if found is not None:
                found.outcomes.append(outcome)

    def finish(self, address: str, status: StepStatus) -> None:
        with self._lock:
            found = self._held.get(address)
            if found is not None:
                found.status = status.value

    def of(self, address: str) -> RunState:
        with self._lock:
            return self._held.get(address) or RunState(address)

    def statuses_under(self, addresses: list[str]) -> list[StepStatus]:
        with self._lock:
            found = [self._held.get(one) for one in addresses]
        return [
            StepStatus(one.status)
            for one in found
            if one is not None and one.status not in (IDLE, RUNNING)
        ]

    def worst_under(self, addresses: list[str]) -> str:
        settled = self.statuses_under(addresses)
        if not settled:
            return IDLE
        return verdict(settled).value

    def clear(self) -> None:
        with self._lock:
            self._held.clear()


RUNS = RunStore()

__all__ = ["IDLE", "RUNNING", "RUNS", "PASSED", "RunState", "RunStore", "address_of", "key_of"]
