"""The fixture's own object, and the link that reaches it."""

from shared import bench_api

PORTS = ("auto", "/dev/ttyACM0", "/dev/ttyACM1")


def serial_ports():
    """Return the ports a board might be on, as a live list would."""
    return PORTS


@bench_api.subsystem(
    "rig",
    """
    One pretend board.

    Stands in for a subsystem so the contract can be exercised without one.
    """,
)
class Rig:
    """Owns nothing, since there is nothing to own."""

    def __init__(self):
        """Start with no link and no history."""
        self.calls = []


@bench_api.link(params=(bench_api.choice("port", serial_ports),))
class RigLink:
    """The pretend connection."""

    def __init__(self):
        """Start disconnected."""
        self.port = None

    def can_connect(self, port) -> bench_api.Readiness:
        """Say whether this port could be opened."""
        if port not in PORTS:
            return bench_api.blocked(f"no board on {port}")
        return bench_api.READY

    def connect(self, port):
        """Open the port, atomically, so a half-configured link is not representable."""
        self.port = port

    def can_disconnect(self) -> bench_api.Readiness:
        """Say whether there is anything to close."""
        return bench_api.READY if self.port else bench_api.blocked("not connected")

    def disconnect(self):
        """Close the port."""
        self.port = None
