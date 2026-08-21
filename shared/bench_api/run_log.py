"""What a run says about itself, written here so no routine writes it again.

A routine yields outcomes to whoever is consuming it, and a screen is the only
consumer there has ever been. So the narrative lived in the browser and died
with the tab: nothing on disk said which routine caused a stretch of traffic,
what it was asked for, or how far it got before it stopped.

Every routine reaches the outside through one generator, which is what makes
that fixable in one place. The weights below are the whole policy: a file takes
DEBUG and a screen takes INFO, so a step that passed is recorded without being
shown, and the two sinks disagree by configuration rather than by a filter.
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

# What the whole run's verdict is worth saying at, which is never less than INFO:
# a run that passed still ends on the screen, even though its steps did not reach it.
RUN_LEVEL = {
    PASSED: "INFO",
    SKIPPED: "INFO",
    WARNED: "WARNING",
    FAILED: "ERROR",
}

# Worst first, so the verdict is the first of these the run produced.
SEVERITY = (FAILED, WARNED, SKIPPED, PASSED)

log = logs.component(COMPONENT)


# ── What names one run ───────────────────────────────────────────────────────


def start_time() -> str:
    """Return the moment a run begins, which with its routine's id names the run.

    Bound once and carried by every line the run causes, so the pair joins a
    stretch of log to anything else filed under the same two. One slot means no
    two runs overlap, which is what makes the pair enough and an identifier
    minted for the purpose unnecessary.

    Microseconds because milliseconds are not enough: two runs of one routine
    can begin inside the same millisecond, and two runs that share a name are
    two runs nothing can tell apart afterwards.
    """
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def verdict(statuses: Sequence[StepStatus]) -> StepStatus:
    """Return the worst status a run produced, which is how the run itself settled."""
    return next((one for one in SEVERITY if one in statuses), PASSED)


# ── What is written ──────────────────────────────────────────────────────────


def write_start(item: Routine, values: Mapping[str, Any]) -> None:
    """Record that a routine began, and what it was asked to run with."""
    log.info("{}{} started", item.id, arguments(values))


def write_step(outcome: StepOutcome) -> None:
    """Record how one step settled, at the weight its status carries."""
    said = f"{outcome.step or 'step'} {outcome.status.value}"
    if outcome.detail:
        said = f"{said}: {outcome.detail}"
    log.log(STEP_LEVEL[outcome.status], "{}", said)


def write_end(item: Routine, statuses: Sequence[StepStatus], seconds: float) -> None:
    """Record how the whole run settled and what it cost."""
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
    """Return what a form submitted as it reads on one line, empty where it held nothing."""
    if not values:
        return ""
    return "(" + ", ".join(f"{name}={value!r}" for name, value in values.items()) + ")"
