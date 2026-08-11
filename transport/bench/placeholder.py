"""A declaration that does the least a declaration can do, and still goes to the board."""

from __future__ import annotations

from typing import Any

from shared import bench_api
from shared.bench_api import Level, Result, StepOutcome, StepStatus


def _greeting(reply: Any) -> str:
    """Return the greeting, naming the firmware that answered it."""
    version = reply.version.split(b"\0", 1)[0].decode("utf-8", "replace")
    return f"Hello world, {version}"


def _fields(reply: Any) -> tuple[tuple[str, str], ...]:
    """Return the rest of what the reply carried, for the panel behind the line."""
    return tuple(
        (name, getattr(reply, name).split(b"\0", 1)[0].decode("utf-8", "replace"))
        for name in ("project", "idf")
    )


@bench_api.bench_test
class SayHello:
    """Say hello.

    One round trip over the open link, which is the least a routine can do and
    still prove the board is there.
    """

    @bench_api.step
    def greet(self, bench: Any) -> StepOutcome:
        """Greeting."""
        reply = bench.firmware.sys.version()
        line = _greeting(reply)
        return StepOutcome(
            StepStatus.PASSED,
            line,
            Result(level=Level.OK, summary=line, fields=_fields(reply)),
        )
