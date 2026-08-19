"""Everything this camera will say about itself, written down while we have it."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from capture import capture
from portable.ccapi import Endpoint, Methods, Setting
from shared import bench_api
from shared.bench_api import (
    PASSED,
    SETUP,
    WARNED,
    Level,
    Result,
    StepOutcome,
    Table,
)

PREFIX = "stef-survey-"
RESPONSES = "responses.json"
SETTINGS = "settings.json"
ABOUT = "about.json"
UNNAMED = "unnamed.json"

NAMED = {str(one) for one in Endpoint} | {str(one) for one in Setting}


def somewhere() -> Path:
    """Return a fresh directory to write into, which nothing here promises to keep."""
    return Path(tempfile.mkdtemp(prefix=PREFIX))


def written(where: Path, name: str, body: Any) -> int:
    """Write one file and say how big it came out."""
    target = where / name
    target.write_text(json.dumps(body, indent=2, sort_keys=True))
    return target.stat().st_size


@bench_api.routine(
    category=SETUP,
    steps=["About", "Manifest", "Read everything", "Settings", "Unnamed"],
    inputs=[
        bench_api.boolean(
            "keep",
            hint="Leave the files on disk. Off deletes them once you have looked.",
        )
    ],
)
def everything(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Ask this camera every question it will answer and write the answers down.

    Verbatim, never parsed: the point is to have something our own reading can
    be checked against, and a stored interpretation would carry the same
    misunderstanding as the code that made it.
    """
    found = capture.camera()
    where = somewhere()
    keep = bool(values.get("keep"))
    total = 0

    device = found.status.device()
    about = {
        "model": device.product_name,
        "serial": device.serial_number,
        "firmware": device.firmware_version,
        "versions": list(found.link.registry.versions),
        "declined": list(found.link.registry.offered_beyond_accepted),
        "taken": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    total += written(where, ABOUT, about)
    yield StepOutcome(PASSED, f"{device.product_name} {device.serial_number}")

    responses: dict[str, Any] = {"/ccapi": found.link.manifest}
    yield StepOutcome(PASSED, f"{len(found.link.registry.features)} endpoints")

    refused: list[tuple[str, ...]] = []
    for feature in found.link.registry.features:
        if Methods.GET not in found.link.registry.methods_for(feature):
            continue
        try:
            responses[feature] = found.link.json("GET", feature)
        except Exception as exc:  # noqa: BLE001
            refused.append((feature, f"{type(exc).__name__}: {exc}"))
    total += written(where, RESPONSES, responses)
    yield StepOutcome(PASSED, f"{len(responses)} answered, {len(refused)} refused")

    said: dict[str, Any] = {}
    for setting in Setting:
        if not found.settings.offers(setting):
            continue
        try:
            value = found.settings.get(setting)
            said[str(setting)] = {"value": value.value, "allowed": list(value.allowed)}
        except Exception as exc:  # noqa: BLE001
            refused.append((str(setting), f"{type(exc).__name__}: {exc}"))
    total += written(where, SETTINGS, said)
    yield StepOutcome(PASSED, f"{len(said)} settings read")

    unnamed = found.link.registry.unnamed(NAMED)
    total += written(where, UNNAMED, list(unnamed))
    summary = (
        f"{len(unnamed)} endpoint(s) this build has no name for"
        if unnamed
        else "every endpoint offered has a name here"
    )
    yield StepOutcome(
        WARNED if unnamed else PASSED,
        summary,
        Result(
            level=Level.WARN if unnamed else Level.OK,
            summary=summary,
            note=(
                f"written to {where}"
                if keep
                else "deleted; tick 'keep' to hold on to it"
            ),
            fields=(("bytes", str(total)), ("refused", str(len(refused)))),
            table=Table(head=("Endpoint",), rows=tuple((one,) for one in unnamed))
            if unnamed
            else None,
        ),
    )
    if not keep:
        shutil.rmtree(where, ignore_errors=True)


@bench_api.routine(
    category=SETUP,
    steps=["Time it"],
    inputs=[bench_api.integer("samples", min=3, max=500)],
)
def round_trip_floor(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Time the cheapest call there is, repeatedly.

    Every other number this bench reports is measured against this one. A fetch
    that takes 400ms means nothing until you know whether an empty round trip
    takes 4ms or 200.
    """
    found = capture.camera()
    samples = int(values.get("samples", 50))
    taken: list[float] = []
    for _ in range(samples):
        started = time.monotonic()
        found.status.battery()
        taken.append((time.monotonic() - started) * 1000)
    taken.sort()
    middle = taken[len(taken) // 2]
    yield StepOutcome(
        PASSED,
        f"{middle:.0f} ms median",
        Result(
            level=Level.OK,
            summary=f"{samples} round trips, {middle:.0f} ms median",
            fields=(
                ("fastest", f"{taken[0]:.0f} ms"),
                ("median", f"{middle:.0f} ms"),
                ("slowest", f"{taken[-1]:.0f} ms"),
            ),
        ),
    )
