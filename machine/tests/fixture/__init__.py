"""A hotplate on a dial, which is subsystem enough to assemble.

One element, one dial, and nothing to plug in.
"""

from shared.subsystem import SubsystemLinkState

_link_state = SubsystemLinkState.DOWN


def link_state() -> SubsystemLinkState:
    return _link_state


def set_link_state(reported: SubsystemLinkState) -> None:
    global _link_state
    _link_state = reported


__all__ = ["link_state", "set_link_state"]
