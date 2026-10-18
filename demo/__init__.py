"""A demo board, with no hardware behind it.

Acts out every behaviour the diagnostics screen can show: tests that pass, warn,
fail and error, questions for the operator, a link that refuses, fails or dies,
and commands that reply or raise. Shown only while STEF_DEMO is set.
"""

from demo.subsystem import Demo

SUBSYSTEM = Demo

__all__ = ["SUBSYSTEM", "Demo"]
