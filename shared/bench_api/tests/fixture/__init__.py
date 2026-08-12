"""An oven with a thermocouple on a serial port, which is subsystem enough to test.

One heating element and the probe watching it.
"""

from shared.bench_api import SubsystemState
from shared.bench_api.tests.fixture.hardware import state

__all__ = ["SubsystemState", "state"]
