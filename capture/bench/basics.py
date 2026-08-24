"""Is this body fit to shoot, and will it take an instruction and give it back."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from capture import capture
from portable.ccapi import Setting, ThermalRestriction
from shared import bench_api
from shared.bench_api import (
    FAILED,
    PASSED,
    SETUP,
    WARNED,
    Abandoned,
    Level,
    Result,
    StepOutcome,
    Table,
)

# The thermal states that stop a scan rather than slow one down.
REFUSING = frozenset(
    {
        ThermalRestriction.STILLS_REFUSED,
        ThermalRestriction.LIVE_VIEW_REFUSED,
        ThermalRestriction.LIVE_VIEW_REFUSED_MOVIE_RESTRICTED,
    }
)

# What a scan reads and writes constantly, so what is worth proving it can.
EXERCISED = (Setting.ISO, Setting.TV)


@bench_api.routine(category=SETUP, steps=["Battery", "Heat"])
def health(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ask the two questions that decide whether a reel can be started at all.

    Both are cheap reads and neither moves anything, so this is what to run
    first and what to run again when something later behaves strangely. A body
    that is hot or nearly flat fails in ways that look like network faults.
    """
    found = capture.camera()

    battery = found.status.battery()
    flat = not battery.present
    yield StepOutcome(
        FAILED if flat else PASSED,
        f"{battery.source.value}, {battery.power.value}",
        Result(
            level=Level.ERROR if flat else Level.OK,
            summary=f"power is {battery.source.value}",
            fields=(
                ("name", battery.name or "--"),
                ("source", battery.source.value),
                ("charge", battery.power.value),
            ),
        ),
    )

    heat = found.status.thermal()
    refusing = heat in REFUSING
    warm = heat is not ThermalRestriction.NORMAL
    summary = (
        "the body is refusing to shoot until it cools"
        if refusing
        else f"the body is warm: {heat.name}"
        if warm
        else "the body is at normal temperature"
    )
    yield StepOutcome(
        FAILED if refusing else WARNED if warm else PASSED,
        heat.name,
        Result(
            level=Level.ERROR if refusing else Level.WARN if warm else Level.OK,
            summary=summary,
            note="nothing else here will behave until this clears" if refusing else None,
        ),
    )


@bench_api.routine(
    category=SETUP, hazardous=True, steps=["Read", "Write", "Put it back"]
)
def read_and_write(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Move ISO and shutter speed one notch and put them back where they were.

    A scan does nothing to a camera but read settings and write them, so the
    cheapest useful proof that the link works in both directions is to do
    exactly that and leave no trace. One notch, because the point is that the
    write took, not what it was set to.
    """
    found = capture.camera()

    started: dict[Setting, str] = {}
    choices: dict[Setting, tuple[str, ...]] = {}
    for setting in EXERCISED:
        if not found.settings.offers(setting):
            continue
        reading = found.settings.get(setting)
        started[setting] = str(reading.value)
        choices[setting] = tuple(str(one) for one in reading.allowed)
    if not started:
        raise Abandoned("this body offers neither ISO nor shutter speed", FAILED)
    yield StepOutcome(
        PASSED, ", ".join(f"{one.name} {started[one]}" for one in started)
    )

    rows: list[tuple[str, ...]] = []
    refused = 0
    for setting, was in started.items():
        wanted = _next_to(was, choices[setting])
        if wanted is None:
            rows.append((setting.name, was, "--", was, "nothing to move to"))
            continue
        found.settings.set(setting, wanted)
        now = str(found.settings.get(setting).value)
        took = now == wanted
        refused += not took
        rows.append((setting.name, was, wanted, now, "took" if took else "refused"))
    yield StepOutcome(
        WARNED if refused else PASSED,
        f"{len(rows) - refused} of {len(rows)} took",
        Result(
            level=Level.WARN if refused else Level.OK,
            summary=f"{len(rows) - refused} of {len(rows)} write(s) took",
            table=Table(
                head=("Setting", "Was", "Asked", "Read back", "Verdict"),
                rows=tuple(rows),
            ),
        ),
    )

    stuck = []
    for setting, was in started.items():
        found.settings.set(setting, was)
        if str(found.settings.get(setting).value) != was:
            stuck.append(setting.name)
    yield StepOutcome(
        FAILED if stuck else PASSED,
        f"{', '.join(stuck)} did not go back" if stuck else "back as it was",
        Result(
            level=Level.ERROR if stuck else Level.OK,
            summary=(
                f"{', '.join(stuck)} is not where this found it"
                if stuck
                else "every setting is back where this found it"
            ),
        )
        if stuck
        else None,
    )


def _next_to(value: str, allowed: tuple[str, ...]) -> str | None:
    """Return a neighbour of `value`, preferring the one after it.

    Either direction proves the same thing, so the one that exists wins. A
    setting with nowhere to move is not a failure, it is a body with one
    option, and the caller says so rather than inventing a value.
    """
    if value not in allowed or len(allowed) < 2:
        return None
    at = allowed.index(value)
    return allowed[at + 1] if at + 1 < len(allowed) else allowed[at - 1]
