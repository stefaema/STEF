"""Finding a camera, and asking whether it will serve us, while nothing holds it."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from capture import capture, probe
from shared import bench_api
from shared.bench_api import (
    FAILED,
    PASSED,
    PRELINK,
    WARNED,
    Level,
    Result,
    StepOutcome,
    Table,
)

HEAD = ("Address", "Model", "Serial", "In use")


@bench_api.routine(category=PRELINK, steps=["Search"])
def search(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Search the network.

    Asks every camera on this subnet to describe itself, out of every interface
    this host has. Multicast does not cross a router and an access point may
    drop it, so silence here means nothing was heard rather than nothing is
    there, and the result says which of those it was.
    """
    swept = probe.sweep()
    if not swept:
        pinned = capture.pinned_host()
        note = (
            f"the configured address {pinned} is still worth trying"
            if pinned
            else "no address is configured either, so there is nothing to connect to"
        )
        yield StepOutcome(
            WARNED,
            swept.sentence,
            Result(level=Level.WARN, summary=swept.sentence, note=note),
        )
        return
    rows = tuple(
        (one.address, one.model or "?", one.serial or "?", "yes" if one.held else "no")
        for one in swept.found
    )
    yield StepOutcome(
        PASSED,
        f"{len(swept.found)} answered",
        Result(
            level=Level.OK,
            summary=swept.sentence,
            table=Table(head=HEAD, rows=rows),
        ),
    )


@bench_api.routine(category=PRELINK, inputs=[], steps=["Ask"])
def whether_it_serves(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ask whether the configured camera will serve us.

    Connects far enough to read the manifest and no further, then lets go. This
    is the same question a blocked Connect button answers, asked on purpose.
    """
    host = capture.settle(capture.AUTO)
    verdict = probe.identify(capture.configured(host))
    if verdict:
        yield StepOutcome(
            PASSED,
            verdict.sentence,
            Result(level=Level.OK, summary=verdict.sentence),
        )
        return
    yield StepOutcome(
        FAILED,
        verdict.sentence,
        Result(level=Level.ERROR, summary=verdict.sentence),
    )
