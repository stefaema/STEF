"""Every shape of routine, declared the way a subsystem declares one."""

from collections.abc import Iterator
from typing import Any

from shared import bench_api
from shared.bench_api import (
    LINK,
    PASSED,
    PRELINK,
    READY,
    WARNED,
    Abandoned,
    Level,
    Option,
    Readiness,
    Result,
    StepOutcome,
    blocked,
)
from shared.bench_api.tests.fixture import hardware
from shared.bench_api.tests.fixture.payloads import RampArgs

WARMING = "Warming"
HOLDING = "Holding"
COOLING = "Cooling"


def ports() -> tuple[Option, ...]:
    """Return the ports the oven might be on, which is a live list."""
    return (Option("/dev/oven0", "oven, front"),)


def probe_is_warm(port: str = "") -> Readiness:
    """Say whether the port named is one this fixture will open."""
    return READY if port.endswith("0") else blocked(f"nothing answers on {port!r}")


# ── The link ─────────────────────────────────────────────────────────────────


@bench_api.routine(
    category=LINK,
    inputs=[bench_api.choice("port", ports)],
    may_run=probe_is_warm,
)
def connect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Connect."""
    hardware.set_state(bench_api.SubsystemState.UP)
    yield StepOutcome(PASSED, f"open on {values['port']}")


@bench_api.routine(category=LINK)
def disconnect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Disconnect."""
    hardware.set_state(bench_api.SubsystemState.DOWN)
    yield StepOutcome(PASSED, "closed")


# ── Before there is a link ───────────────────────────────────────────────────


@bench_api.routine(category=PRELINK, steps=[WARMING, HOLDING])
def check_probe(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Check the probe.

    Reads the thermocouple twice, which needs the port to itself.
    """
    yield StepOutcome(PASSED, "probe reads 21 C")
    yield StepOutcome(WARNED, "drifted 2 C", Result(level=Level.WARN, summary="drift"))


# ── With a link ──────────────────────────────────────────────────────────────


@bench_api.routine(hazardous=True, steps=[WARMING, HOLDING, COOLING])
def ramp(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ramp the oven.

    Warms it, holds it, and lets it cool.
    """
    yield StepOutcome(PASSED, f"warming to {values.get('celsius', 0)}")
    yield StepOutcome(PASSED, "held", step=HOLDING)
    yield StepOutcome(PASSED, "cooled", step=COOLING)


@bench_api.routine(steps=[WARMING, HOLDING, COOLING])
def ramp_that_gives_up(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ramp, and find there is nothing to do."""
    yield StepOutcome(PASSED, "warming")
    raise Abandoned("already at temperature", PASSED)


@bench_api.routine(steps=[WARMING, HOLDING])
def ramp_that_breaks(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ramp, and hit something nobody caught."""
    yield StepOutcome(PASSED, "warming")
    raise RuntimeError("the element is open circuit")


@bench_api.routine()
def read_each_step(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Read as many times as it takes, which nobody can preview."""
    for reading in (21, 22):
        yield StepOutcome(PASSED, f"{reading} C")


@bench_api.routine(inputs=bench_api.inputs_for(RampArgs))
def derived_form(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Take a form nobody wrote out by hand."""
    yield StepOutcome(PASSED, "taken")


@bench_api.routine(steps=[WARMING, HOLDING])
def ramp_that_never_starts(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Fail before any step settles."""
    raise ValueError("no oven here")
    yield  # pragma: no cover


bench_api.register_routine(
    module=__name__,
    group="generated",
    name="ramp_once",
    title="Ramp once",
    description="Registered from parts, the way a generated family is.",
    hazardous=True,
    inputs=[bench_api.integer("celsius", unit="C", max=300)],
    run=lambda values: iter([StepOutcome(PASSED, f"{values['celsius']} C")]),
)
