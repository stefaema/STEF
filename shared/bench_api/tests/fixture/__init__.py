"""An oven with a thermocouple on a serial port, which is subsystem enough to test.

One heating element and the probe watching it.
"""

from shared.bench_api import SubsystemLinkState
from shared.bench_api.tests.fixture.hardware import link_state

__all__ = ["SubsystemLinkState", "link_state"]
