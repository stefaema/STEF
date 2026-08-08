"""The fixture's actions, declaring only what an annotation cannot carry."""

from shared import bench_api
from shared.bench_api import Button, Digest, Layer, Span
from shared.bench_api.tests.fixture.payloads import (
    ClearArgs,
    MoveArgs,
    ReadArgs,
    SendArgs,
    WriteArgs,
)


def devices():
    """Return the device list, as a live catalog would."""
    return ("capstan", "supply", "takeup")


def write_digest(values) -> Digest:
    """Return what a write puts on the wire, without putting it there."""
    body = bytes([values.get("idx", 0), len(values.get("ops", ()))])
    return Digest(
        layers=(
            Layer(
                title="Request payload",
                body=body,
                legend=(Span("idx", 0, 1), Span("count", 1, 1)),
                buttons=(Button(label="Send", call="raw.write(...)", hazardous=True),),
            ),
        )
    )


@bench_api.action("raw.read")
def read(args: ReadArgs):
    """Read one register.

    Answers from the cache when the slot is still valid.
    """


@bench_api.action("raw.write", hazardous=True, digest=write_digest)
def write(args: WriteArgs):
    """Write a batch of registers."""


@bench_api.action(
    "raw.move",
    hazardous=True,
    params=(bench_api.integer("cruise_pps", unit="pps", max=3200),),
)
def move(args: MoveArgs):
    """Start a run."""


@bench_api.action("raw.clear_faults")
def clear_faults(args: ClearArgs):
    """Acknowledge the latched faults named."""


@bench_api.action("relay.send")
def send(args: SendArgs):
    """Put a datagram on the wire unaltered."""


@bench_api.action("sys.version")
def version():
    """Report the protocol version.

    Takes no arguments, and still renders.
    """
