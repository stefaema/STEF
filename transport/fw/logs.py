"""Firmware log lines, written to the PC's log."""

from shared import logs
from transport.fw import framing

# Wire log levels from `rpc_proto.h`, as loguru level names.
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
    """Log one firmware line at its arrival time, prefixed with the board's uptime."""
    log.log(
        LEVELS.get(record.level, UNKNOWN),
        "+{}ms {}",
        record.uptime_ms,
        record.text.rstrip(),
    )
