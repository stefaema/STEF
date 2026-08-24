"""The board's own log lines, in the shape everything else here writes."""

from __future__ import annotations

from shared import logs
from transport.fw import framing

# The severity band `rpc_proto.h` fixes on the wire, as the names a sink knows.
LEVELS = {
    0: "INFO",
    1: "ERROR",
    2: "WARNING",
    3: "INFO",
    4: "DEBUG",
    5: "TRACE",
}
UNKNOWN = "INFO"

log = logs.as_component("transport.firmware")


def forward(record: framing.LogRecord) -> None:
    """Write one firmware line, stamped when we received it and saying when it was said.

    The board has no clock, only its own uptime, and a reset restarts it. So the
    timestamp is honestly ours, the arrival, and the board's number rides in the
    message where it can still be matched against a firmware-side trace.
    """
    log.log(
        LEVELS.get(record.level, UNKNOWN),
        "+{}ms {}",
        record.uptime_ms,
        record.text.rstrip(),
    )
