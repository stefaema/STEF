"""One line, one shape, one file, whatever said it."""

from __future__ import annotations

import inspect
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from shared import paths

FILENAME = "stef.log"
ROTATION = "10 MB"
BUDGET = 1_000_000_000
DEFAULT_COMPONENT = "stef"
WIDTH = 20

FILE_FORMAT = (
    "[{level: <8}] {time:YYYY-MM-DD HH:mm:ss.SSS} [{extra[component]: <20}] {message}"
)
CONSOLE_FORMAT = (
    "<level>[{level: <8}]</level> <dim>{time:HH:mm:ss.SSS}</dim> "
    "[<cyan>{extra[component]: <20}</cyan>] {message}"
)

__all__ = [
    "BUDGET",
    "CONSOLE_FORMAT",
    "FILE_FORMAT",
    "ROTATION",
    "component",
    "intercept_stdlib",
    "keep_under",
    "logger",
    "start",
    "to",
]


# ── What is kept ─────────────────────────────────────────────────────────────


def keep_under(limit: int) -> Callable[[list[str]], None]:
    """Return a retention that drops the oldest archives once they pass a budget."""

    def retention(files: list[str]) -> None:
        files.sort(key=os.path.getmtime, reverse=True)
        total = 0
        for index, path in enumerate(files):
            total += os.path.getsize(path)
            if total > limit and index > 0:
                os.remove(path)

    return retention


# ── Who is speaking ──────────────────────────────────────────────────────────


def component(name: str) -> Any:
    """Return a logger that names its component on every line it writes."""
    return logger.bind(component=name)


# ── Where lines go ───────────────────────────────────────────────────────────


def start(
    directory: Path | None = None,
    file_level: str = "DEBUG",
    console_level: str | None = "INFO",
    rotation: str = ROTATION,
    budget: int = BUDGET,
) -> Path:
    """Take every sink down and put the file and console back up.

    Returns the file being written, which is what an operator is told to send.
    """
    logger.remove()
    logger.configure(extra={"component": DEFAULT_COMPONENT})

    if console_level is not None:
        logger.add(sys.stderr, format=CONSOLE_FORMAT, level=console_level)

    target = directory or paths.log_dir()
    target.mkdir(parents=True, exist_ok=True)
    written = target / FILENAME
    logger.add(
        written,
        format=FILE_FORMAT,
        level=file_level,
        rotation=rotation,
        retention=keep_under(budget),
        compression="zip",
        enqueue=True,
        diagnose=False,
        backtrace=True,
    )
    intercept_stdlib()
    return written


def to(sink: Callable[[Any], None], level: str = "INFO") -> int:
    """Add one more sink, which is how a screen receives what a file records."""
    return logger.add(sink, level=level, format=FILE_FORMAT)


# ── Lines written to the standard library ────────────────────────────────────


class _Intercept(logging.Handler):
    """Every stdlib record, forwarded so a library needs no logging dependency."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record, keeping the level and the frame it came from."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame = inspect.currentframe()
        depth = 0
        while frame is not None and (
            depth == 0 or frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1
        logger.bind(component=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


def intercept_stdlib(level: int = logging.DEBUG) -> None:
    """Point the standard library's root logger at this one, and only this one."""
    logging.basicConfig(handlers=[_Intercept()], level=level, force=True)
