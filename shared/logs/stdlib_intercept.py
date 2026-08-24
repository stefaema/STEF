"""Everything the standard library's logging costs us, behind one door.

Nothing in here is a concept of this project. `logging` hands a record over in
its own shape, and loguru wants a different one, so the vocabulary below is
inherited from those two APIs rather than chosen: what a record reserves for
itself, and how many frames back the caller is.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from loguru import logger

__all__ = ["intercept_stdlib"]


# Every attribute the standard library puts on a record itself. `taskName` joined
# them in 3.12, and this package supports 3.11.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "taskName"
}


def _attached(record: logging.LogRecord) -> dict[str, Any]:
    """Return what a caller passed as `extra`."""
    return {
        name: value for name, value in record.__dict__.items() if name not in _RESERVED
    }


def _depth_to_caller() -> int:
    """Return how many frames back the code that logged is, for loguru to stamp.

    Loguru names a line's origin by walking the stack. Every frame between here
    and the caller belongs to `logging`, so without this each intercepted line
    would be attributed to the standard library rather than to whoever spoke.
    """
    here = inspect.currentframe()
    frame = here.f_back if here is not None else None
    depth = 0
    while frame is not None and (
        depth == 0 or frame.f_code.co_filename == logging.__file__
    ):
        frame = frame.f_back
        depth += 1
    return depth


class _Intercept(logging.Handler):
    """Every stdlib record, forwarded so a library needs no logging dependency."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record, keeping its level, its calling frame and its `extra`."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        bound = {"component": record.name, **_attached(record)}
        logger.bind(**bound).opt(
            depth=_depth_to_caller(), exception=record.exc_info
        ).log(level, record.getMessage())


def intercept_stdlib(level: int = logging.DEBUG) -> None:
    """Replace every root handler with one that forwards to this logger."""
    logging.basicConfig(handlers=[_Intercept()], level=level, force=True)
