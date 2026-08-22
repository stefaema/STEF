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

HEAD = ("Address", "Model", "Serial", "CCAPI")


@bench_api.routine(category=PRELINK, steps=["Search"])
def search(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Search the network.

    Asks every camera on this subnet to describe itself. Multicast does not
    cross a router and a switch may drop it, so silence here means nothing was
    heard rather than nothing is there.
    """
    found = probe.search()
    if not found:
        pinned = capture.pinned_host()
        detail = "nothing answered"
        note = (
            f"the configured address {pinned} is still worth trying"
            if pinned
            else "no address is configured either, so there is nothing to connect to"
        )
        yield StepOutcome(
            WARNED, detail, Result(level=Level.WARN, summary=detail, note=note)
        )
        return
    rows = tuple(
        (one.host, one.model or "?", one.serial or "?", "on" if one.serving else "off")
        for one in found
    )
    yield StepOutcome(
        PASSED,
        f"{len(found)} answered",
        Result(
            level=Level.OK,
            summary=f"{len(found)} camera(s) answered",
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
