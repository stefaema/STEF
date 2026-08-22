"""The state this fixture's package reports, and the knob that moves it."""

from shared.bench_api import SubsystemLinkState

_link_state = SubsystemLinkState.DOWN


def link_state() -> SubsystemLinkState:
    """Return whether the oven is reachable."""
    return _link_state


def set_link_state(now: SubsystemLinkState) -> None:
    """Put the oven in a state, which is what a test needs that an operator does not."""
    global _link_state
    _link_state = now
