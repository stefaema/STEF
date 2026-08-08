"""One record on the stream every subsystem writes to."""

from dataclasses import dataclass

from shared.bench_api.state import Level


@dataclass(frozen=True, slots=True)
class Event:
    """One line on the log: who said it, how loud, and when."""

    time: float
    source: str
    level: Level
    text: str
