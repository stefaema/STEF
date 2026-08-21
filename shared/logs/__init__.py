"""One line, one shape, one file, whatever said it.

Two dialects reach it. A module under `portable/` may depend on nothing, so it
speaks the standard library and is intercepted here. Everything else binds a
component and speaks this module directly. Both arrive as one record: a routine
in scope binds itself onto whichever is speaking, and `extra` survives from
either, so the dialect a module speaks costs it no detail.
"""

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
ROUTINE = "[{extra[routine]}] "
MESSAGE = "{message}"

FILE_FORMAT = HEAD + MESSAGE
CONSOLE_FORMAT = (
    "<level>[{level: <8}]</level> <dim>{time:HH:mm:ss.SSS}</dim> "
    "[<cyan>{extra[component]: <20}</cyan>] " + ROUTINE + MESSAGE
)

__all__ = [
    "BUDGET",
    "CONSOLE_FORMAT",
    "DEFAULTS",
    "FILE_FORMAT",
    "ROTATION",
    "component",
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
    """Return the template one record renders through, naming a routine only where it ran under one.

    A fixed column would print empty brackets on every line the bench did not
    cause, which is most of them. The ending and the traceback are ours to add
    here, since loguru only appends those for a template it was handed whole.
    """
    named = ROUTINE if record["extra"].get("routine") else ""
    return f"{HEAD}{named}{MESSAGE}\n{{exception}}"


# ── Where lines go ───────────────────────────────────────────────────────────


def start(
    directory: Path | None = None,
    file_level: str = "DEBUG",
    console_level: str | None = "INFO",
    rotation: str = ROTATION,
    budget: int = BUDGET,
) -> Path:
    """Take every sink down and put the file and console back up.

    The file is JSON, one object per line, and each object carries the rendered
    line under `text` as well as every bound field under `record.extra`. So it
    reads back as the plain log through `jq -r .text` and joins on a routine or
    a run without anything having to be parsed out of a sentence.

    Returns the file being written, which is what an operator is told to send.
    """
    logger.remove()
    logger.configure(extra=dict(DEFAULTS))

    if console_level is not None:
        logger.add(sys.stderr, format=CONSOLE_FORMAT, level=console_level)

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
    """Add one more sink, which is how a screen receives what a file records.

    INFO by default, and that default is the whole of the difference between
    what is kept and what is shown: a step that passed is written at DEBUG and
    reaches the file alone.
    """
    return logger.add(sink, level=level, format=template_for)


# ── Lines written to the standard library ────────────────────────────────────


# Every attribute the standard library puts on a record itself. What is left over
# is what a caller attached, and meant to travel with the line.
RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def attached(record: logging.LogRecord) -> dict[str, Any]:
    """Return the fields a caller passed as `extra`, which is everything not the record's own."""
    return {
        name: value for name, value in record.__dict__.items() if name not in RESERVED
    }


class _Intercept(logging.Handler):
    """Every stdlib record, forwarded so a library needs no logging dependency."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record, keeping the level, the frame and whatever was attached.

        A module that may not depend on this one still has something to say
        beyond a sentence, and `extra` is how the standard library says it. Kept
        so the two dialects reach the file carrying the same weight of detail.
        """
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
