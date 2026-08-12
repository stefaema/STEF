"""The state this fixture's package reports, and the knob that moves it."""

from shared.bench_api import SubsystemState

_state = SubsystemState.DOWN


def state() -> SubsystemState:
    """Return whether the oven is reachable."""
    return _state


def set_state(now: SubsystemState) -> None:
    """Put the oven in a state, which is what a test needs that an operator does not."""
    global _state
    _state = now
