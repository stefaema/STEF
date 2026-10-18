from __future__ import annotations

import time

from demo.board import TARGETS
from shared.subsystem import choice

PACE_S = 0.4

TARGET = choice(
    "board",
    TARGETS,
    hint="How the demo board should behave when you connect to it.",
)


def pause(times: float = 1.0) -> None:
    time.sleep(PACE_S * times)
