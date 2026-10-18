"""
Every run's log print.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from shared import logs
from shared.diagnostics.records import (
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    WARNED,
    StepOutcome,
    StepStatus,
    verdict,
)

COMPONENT = "diagnostics"

# What one step's status is worth saying at.
STEP_LEVEL = {
    PASSED: "DEBUG",
    SKIPPED: "DEBUG",
    WARNED: "WARNING",
    FAILED: "ERROR",
    ERROR: "ERROR",
}

# What the whole run's verdict is worth saying at.
RUN_LEVEL = {
    PASSED: "INFO",
    SKIPPED: "INFO",
    WARNED: "WARNING",
    FAILED: "ERROR",
    ERROR: "ERROR",
}

log = logs.as_component(COMPONENT)


# ── What names one run ───────────────────────────────────────────────────────


def start_time() -> str:
    """Return when a run begins. With its routine's id, this names the run."""
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


# ── What is written ──────────────────────────────────────────────────────────


def write_start(name: str, values: Mapping[str, Any]) -> None:
    """Record that a routine began, and with what."""
    log.info("{}{} started", name, arguments(values))


def write_step(outcome: StepOutcome) -> None:
    """Record how one step settled, at the weight its status carries."""
    said = f"{outcome.step} {outcome.status.value}" if outcome.step else ""
    said = said or outcome.status.value
    if outcome.detail:
        said = f"{said}: {outcome.detail}"
    log.log(STEP_LEVEL[outcome.status], "{}", said)


def write_end(name: str, statuses: Sequence[StepStatus], seconds: float) -> None:
    """Record the run's verdict and what it cost."""
    settled = verdict(statuses)
    log.log(
        RUN_LEVEL[settled],
        "{} {} in {:.2f} s, {} step(s)",
        name,
        settled.value,
        seconds,
        len(statuses),
    )


def write_command(name: str, values: Mapping[str, Any]) -> None:
    log.info("{}{}", name, arguments(values))


def arguments(values: Mapping[str, Any]) -> str:
    """Return submitted values on one line, empty where there were none."""
    if not values:
        return ""
    return "(" + ", ".join(f"{name}={value!r}" for name, value in values.items()) + ")"
