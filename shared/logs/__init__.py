"""Log system of the STEF project"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from shared import paths
from shared.logs.stdlib_intercept import intercept_stdlib

FILENAME = "stef.jsonl"
ROTATION = "10 MB"
BUDGET = 1_000_000_000  # 1 GB
DEFAULT_COMPONENT = "stef"

# Every field a format below names, so a record nobody bound still renders.
DEFAULTS = {"component": DEFAULT_COMPONENT, "routine": ""}

HEAD = "[{level: <8}] {time:YYYY-MM-DD HH:mm:ss.SSS} [{extra[component]: <20}] "
CONSOLE_HEAD = (
    "<level>[{level: <8}]</level> <dim>{time:HH:mm:ss.SSS}</dim> "
    "[<cyan>{extra[component]: <20}</cyan>] "
)
ROUTINE = "[{extra[routine]}] "
CONSOLE_ROUTINE = "<magenta>[{extra[routine]}]</magenta> "
MESSAGE = "{message}"

__all__ = [
    "BUDGET",
    "DEFAULTS",
    "ROTATION",
    "as_component",
    "capped_at",
    "console_format",
    "file_format",
    "intercept_stdlib",
    "logger",
    "start",
    "to",
]


# ── What is kept ─────────────────────────────────────────────────────────────


def capped_at(limit: int) -> Callable[[list[str]], None]:
    """Return a retention that drops the oldest archives once the total passes a limit."""

    def retention(files: list[str]) -> None:
        files.sort(key=os.path.getmtime, reverse=True)
        total = 0
        for index, path in enumerate(files):
            total += os.path.getsize(path)
            if total > limit and index > 0:
                os.remove(path)

    return retention


# ── Who is speaking ──────────────────────────────────────────────────────────


def as_component(name: str) -> Any:
    """Return a logger that names its component on every line it writes."""
    return logger.bind(component=name)


def file_format(record: Any) -> str:
    """Return the template loguru renders one record with, for the file."""
    return _format(record, HEAD, ROUTINE)


def console_format(record: Any) -> str:
    """Return the same template a file gets, coloured for a terminal."""
    return _format(record, CONSOLE_HEAD, CONSOLE_ROUTINE)


def _format(record: Any, head: str, routine: str) -> str:
    """Return a template naming a routine only where the record ran under one.

    A fixed column would print empty brackets on most lines. The ending and the
    traceback are ours to add: loguru appends those only to a plain template.
    """
    named = routine if record["extra"].get("routine") else ""
    return f"{head}{named}{MESSAGE}\n{{exception}}"


# ── Where lines go ───────────────────────────────────────────────────────────


def start(
    directory: Path | None = None,
    file_level: str = "DEBUG",
    console_level: str | None = "INFO",
    rotation: str = ROTATION,
    budget: int = BUDGET,
) -> Path:
    """Take every sink down, put the file and console back up, and return the file."""
    logger.remove()
    logger.configure(extra=dict(DEFAULTS))

    if console_level is not None:
        logger.add(sys.stderr, format=console_format, level=console_level)

    target = paths.ensure(directory or paths.log_dir())
    written = target / FILENAME
    logger.add(
        written,
        format=file_format,
        serialize=True,
        level=file_level,
        rotation=rotation,
        retention=capped_at(budget),
        compression="zip",
        enqueue=True,
        diagnose=False,
        backtrace=True,
    )
    intercept_stdlib()
    return written


def to(sink: Callable[[Any], None], level: str = "INFO") -> int:
    """Add one more sink, which is how a screen receives what a file records."""
    return logger.add(sink, level=level, format=file_format)
