"""Opening and closing the link, which is the one thing everything else waits on."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from shared import bench_api
from shared.bench_api import (
    LINK,
    PASSED,
    READY,
    Level,
    Readiness,
    Result,
    StepOutcome,
    blocked,
)
from transport import fw, transport
from transport.transport import AUTO, installed_version, named_port, serial_ports

PORT = bench_api.choice(
    "port",
    serial_ports,
    hint="Which port the board is on. 'auto' when it is the only one.",
)


# ── Whether there is anything to open or close ───────────────────────────────


def link_is_down() -> Readiness:
    """Say whether there is no link yet, which is what connecting needs."""
    if transport.state() is bench_api.SubsystemState.UP:
        return blocked("already connected")
    return READY


def link_is_up() -> Readiness:
    """Say whether there is a link to close."""
    if transport.state() is bench_api.SubsystemState.UP:
        return READY
    return blocked("not connected")


def can_connect(port: str = AUTO) -> Readiness:
    """Say whether our firmware is answering on this port, and what is there when not.

    Asks rather than remembering whether a verify panel was run. A remembered
    answer goes stale on the next replug, and the refusal an operator can act on
    is the one that names what it found.
    """
    try:
        chosen = fw.probe.find_port(named_port(port))
    except fw.link.LinkError as exc:
        return blocked(str(exc))
    verdict = fw.probe.identify(chosen, installed_version())
    return READY if verdict else blocked(verdict.sentence)


# ── The two routines ─────────────────────────────────────────────────────────


@bench_api.routine(
    category=LINK, inputs=[PORT], can_run=link_is_down, can_run_with=can_connect
)
def connect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Connect.

    Opens the port and puts nothing on the wire beyond the question of who is
    answering on it.
    """
    chosen = transport.open_link(values.get("port", AUTO))
    yield StepOutcome(
        PASSED,
        f"connected on {chosen}",
        Result(level=Level.OK, summary=f"the link is open on {chosen}"),
    )


@bench_api.routine(category=LINK, can_run=link_is_up)
def disconnect(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Disconnect.

    Closes the link and every thread it started, whatever state it was in.
    """
    transport.close_link()
    yield StepOutcome(PASSED, "disconnected")
