"""Every run's account of itself, written here rather than by each routine.

Outcomes only ever reached the consumer, so the account died with the screen.
Level is the whole policy: the file takes DEBUG, a screen INFO. A passing step
is kept without being shown.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from shared import logs
from shared.bench_api.records import (
    FAILED,
    PASSED,
    SKIPPED,
    WARNED,
    Routine,
    StepOutcome,
    StepStatus,
)

COMPONENT = "bench_api"

# What one step's status is worth saying at.
STEP_LEVEL = {
    PASSED: "DEBUG",
    SKIPPED: "DEBUG",
    WARNED: "WARNING",
    FAILED: "ERROR",
}

# What the whole run's verdict is worth saying at.
RUN_LEVEL = {
    PASSED: "INFO",
    SKIPPED: "INFO",
    WARNED: "WARNING",
    FAILED: "ERROR",
}

# Worst first, so the verdict is the first of these the run produced.
SEVERITY = (FAILED, WARNED, PASSED, SKIPPED)

log = logs.component(COMPONENT)


# ── What names one run ───────────────────────────────────────────────────────


def start_time() -> str:
    """Return when a run begins. With its routine's id, this names the run.

    Microseconds: two runs of one routine can share a millisecond.
    """
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def verdict(statuses: Sequence[StepStatus]) -> StepStatus:
    """Return the worst status a run produced."""
    return next((one for one in SEVERITY if one in statuses), PASSED)


# ── What is written ──────────────────────────────────────────────────────────


def write_start(item: Routine, values: Mapping[str, Any]) -> None:
    """Record that a routine began, and with what."""
    log.info("{}{} started", item.id, arguments(values))


def write_step(outcome: StepOutcome) -> None:
    """Record how one step settled, at the weight its status carries."""
    said = outcome.status.value
    if named(outcome.step):
        said = f"{outcome.step} {said}"
    if outcome.detail:
        said = f"{said}: {outcome.detail}"
    log.log(STEP_LEVEL[outcome.status], "{}", said)


def named(step: str) -> bool:
    """Whether a step's title says anything. The `#n` fallback does not."""
    return bool(step) and not step.startswith("#")


def write_end(item: Routine, statuses: Sequence[StepStatus], seconds: float) -> None:
    """Record the run's verdict and what it cost."""
    settled = verdict(statuses)
    log.log(
        RUN_LEVEL[settled],
        "{} {} in {:.2f} s, {} step(s)",
        item.id,
        settled.value,
        seconds,
        len(statuses),
    )


def arguments(values: Mapping[str, Any]) -> str:
    """Return submitted values on one line, empty where there were none."""
    if not values:
        return ""
    return "(" + ", ".join(f"{name}={value!r}" for name, value in values.items()) + ")"
