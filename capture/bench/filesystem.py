"""The card: how full it is, what is on it, and what a whole round trip costs."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from capture import capture
from capture.bench.shots import landed, swept
from portable.ccapi import ContentKind, PollWait
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

GIGABYTE = 1_000_000_000
FRAME_BYTES = 8_000_000
REEL = 16_000


def megabytes(count: int) -> str:
    """Return a byte count as the number a person would say out loud."""
    return f"{count / 1_000_000:.1f} MB"


@bench_api.routine(category=SETUP, steps=["Read"])
def cards(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Read what media is mounted and how much of it is left.

    `contentsnumber` comes back in the same call, which is the only way to ask
    "did every frame land" without moving a single image.
    """
    found = capture.camera().filesystem.storages()
    if not found:
        raise Abandoned("no media is mounted", FAILED)
    rows = tuple(
        (
            one.name,
            one.access.value,
            megabytes(one.capacity),
            megabytes(one.free),
            str(one.file_count),
            "yes" if one.holds(REEL, FRAME_BYTES) else "no",
        )
        for one in found
    )
    yield StepOutcome(
        PASSED,
        f"{len(found)} mounted",
        Result(
            level=Level.OK,
            summary=f"{len(found)} card(s) mounted",
            note=f"'holds a reel' is {REEL} frames at {megabytes(FRAME_BYTES)} each",
            table=Table(
                head=("Card", "Access", "Capacity", "Free", "Files", "Holds a reel"),
                rows=rows,
            ),
        ),
    )


@bench_api.routine(category=SETUP, steps=["Volumes", "Directories", "Files"])
def browse(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Walk the card the way the protocol makes you: storages, then folders, then files.

    Three round trips before a single filename, which is why nothing on the scan
    path walks: a capture reports its own path on the event stream.
    """
    files = capture.camera().filesystem
    volumes = files.volumes()
    yield StepOutcome(PASSED, f"{len(volumes)} volume(s)")
    if not volumes:
        raise Abandoned("no volumes to walk", FAILED)

    directories = files.directories(volumes[0])
    yield StepOutcome(PASSED, f"{len(directories)} directory/ies")
    if not directories:
        raise Abandoned("no directories on this card")

    listed = files.files_in(directories[0])
    rows = tuple((one.rsplit("/", 1)[-1],) for one in listed[:20])
    yield StepOutcome(
        PASSED,
        f"{len(listed)} file(s)",
        Result(
            level=Level.OK,
            summary=f"{len(listed)} file(s) in {directories[0].rsplit('/', 1)[-1]}",
            note="first twenty shown" if len(listed) > 20 else None,
            table=Table(head=("File",), rows=rows),
        ),
    )


@bench_api.routine(
    category=SETUP,
    hazardous=True,
    steps=["Fire", "Confirm", "Thumbnail", "Full size", "Discard"],
)
def round_trip(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Take a frame, fetch it both ways, then delete it, leaving the card as it was.

    The throughput this reports is the number the whole download design rests
    on: whether frames can come off during a scan, or whether the card is the
    only path fast enough.
    """
    found = capture.camera()
    found.events.poll(PollWait.IMMEDIATELY)
    found.shooting.capture(af=False)
    yield StepOutcome(PASSED, "fired")

    paths = landed(found)
    if not paths:
        raise Abandoned("nothing landed to fetch", FAILED)
    path = paths[0]
    yield StepOutcome(PASSED, path.rsplit("/", 1)[-1])

    started = time.monotonic()
    small = found.filesystem.fetch(path, ContentKind.THUMBNAIL)
    thumb_time = time.monotonic() - started
    yield StepOutcome(
        PASSED,
        f"thumbnail {megabytes(len(small))} in {thumb_time:.2f} s",
    )

    started = time.monotonic()
    whole = found.filesystem.fetch(path, ContentKind.MAIN)
    main_time = time.monotonic() - started
    rate = len(whole) / main_time / 1_000_000 if main_time else 0.0
    reel_hours = (REEL * len(whole) / (rate * 1_000_000) / 3600) if rate else 0.0
    slow = rate < 10.0
    yield StepOutcome(
        WARNED if slow else PASSED,
        f"{rate:.1f} MB/s",
        Result(
            level=Level.WARN if slow else Level.OK,
            summary=f"{megabytes(len(whole))} in {main_time:.2f} s, {rate:.1f} MB/s",
            note=(
                f"a {REEL} frame reel would take {reel_hours:.1f} h to pull over this link"
                if rate
                else None
            ),
            fields=(
                ("thumbnail", megabytes(len(small))),
                ("full size", megabytes(len(whole))),
                ("throughput", f"{rate:.1f} MB/s"),
            ),
        ),
    )
    yield StepOutcome(PASSED, f"{swept(found, paths)} removed")
