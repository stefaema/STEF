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

FILENAME = "stef.jsonl"
ROTATION = "10 MB"
BUDGET = 1_000_000_000
DEFAULT_COMPONENT = "stef"
WIDTH = 20

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

FILE_FORMAT = HEAD + MESSAGE
CONSOLE_FORMAT = CONSOLE_HEAD + MESSAGE

__all__ = [
    "BUDGET",
    "CONSOLE_FORMAT",
    "CONSOLE_HEAD",
    "DEFAULTS",
    "FILE_FORMAT",
    "ROTATION",
    "component",
    "console_template_for",
    "intercept_stdlib",
    "keep_under",
    "RESERVED",
    "attached",
    "logger",
    "start",
    "template_for",
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


def template_for(record: Any) -> str:
    """Return one record's template for the file."""
    return _template(record, HEAD, ROUTINE)


def console_template_for(record: Any) -> str:
    """Return one record's template for a screen, which is the same but coloured."""
    return _template(record, CONSOLE_HEAD, CONSOLE_ROUTINE)


def _template(record: Any, head: str, routine: str) -> str:
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
        logger.add(sys.stderr, format=console_template_for, level=console_level)

    target = directory or paths.log_dir()
    target.mkdir(parents=True, exist_ok=True)
    written = target / FILENAME
    logger.add(
        written,
        format=template_for,
        serialize=True,
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
    return logger.add(sink, level=level, format=template_for)


# ── Lines written to the standard library ────────────────────────────────────


# Every attribute the standard library puts on a record itself.
RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def attached(record: logging.LogRecord) -> dict[str, Any]:
    """Return what a caller passed as `extra`."""
    return {
        name: value for name, value in record.__dict__.items() if name not in RESERVED
    }


class _Intercept(logging.Handler):
    """Every stdlib record, forwarded so a library needs no logging dependency."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record with its level, frame and `extra`, which is lost otherwise."""
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
        bound = {"component": record.name, **attached(record)}
        logger.bind(**bound).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def intercept_stdlib(level: int = logging.DEBUG) -> None:
    """Point the standard library's root logger at this one, and only this one."""
    logging.basicConfig(handlers=[_Intercept()], level=level, force=True)
