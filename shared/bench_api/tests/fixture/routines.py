"""The fixture's bench tests, in both of the forms the contract accepts.

Nothing here is named `test_*`, or pytest and `ci_cd.discovery.has_py_tests()`
would collect it.
"""

from shared import bench_api
from shared.bench_api import Outcome, Status


@bench_api.bench_test
class General:
    """General check.

    Reads the version, the state and the board table.
    """

    @bench_api.step
    def version(self, bench):
        """Protocol version."""
        return Outcome(Status.PASSED, "protocol 1")

    @bench_api.step
    def state(self, bench):
        """Firmware state."""
        return Outcome(Status.PASSED, "idle, ready")

    @bench_api.step
    def devices(self, bench):
        """Board table."""
        return Outcome(Status.WARNED, "1 device, expected 3")


@bench_api.bench_test(hazardous=True)
class Ramp:
    """Acceleration ramp.

    Emits a profile and compares the declared count against the emitted one.
    Moves the capstan.
    """

    def __init__(self):
        """Start with nothing emitted, so the steps can share it."""
        self.emitted = 0

    @bench_api.step
    def enable(self, bench):
        """Enable the stage."""
        return Outcome(Status.PASSED, "stage enabled")

    @bench_api.step
    def run(self, bench):
        """Run of 4000 pulses."""
        self.emitted = 4000
        return Outcome(Status.PASSED, f"emitted {self.emitted}")

    @bench_api.step
    def counted(self, bench):
        """Pulses emitted."""
        return Outcome(Status.PASSED, f"emitted {self.emitted}, running 0")


@bench_api.bench_test
def sweep(bench):
    """Register sweep.

    The generator form.
    """
    yield Outcome(Status.PASSED, "protocol 1")
    yield Outcome(Status.PASSED, "idle, ready")
    yield Outcome(Status.WARNED, "1 device, expected 3")


@bench_api.bench_test
class Otp:
    """OTP read.

    Raises before any step settles.
    """

    @bench_api.step
    def dump(self, bench):
        """OTP dump."""
        raise PermissionError("OTP_READ is not in this firmware's access policy")


@bench_api.link_test
class IdentifyBoard:
    """Identify the board.

    Reads the descriptor without opening a link.
    """

    @bench_api.step
    def descriptor(self, bench):
        """USB descriptor."""
        return Outcome(Status.PASSED, "one board")
