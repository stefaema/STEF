"""A hotplate on a dial, which is subsystem enough to assemble.

One element, one dial, and nothing to plug in.
"""

from shared.subsystem import SubsystemState

_state = SubsystemState.DOWN


def state() -> SubsystemState:
    return _state


def set_state(reported: SubsystemState) -> None:
    global _state
    _state = reported


__all__ = ["set_state", "state"]
