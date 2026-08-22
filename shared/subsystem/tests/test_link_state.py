"""What a package reports when asked for its state."""

from types import SimpleNamespace

from shared.subsystem import SubsystemLinkState, link_state_of


def test_a_package_reporting_nothing_is_down():
    assert link_state_of(SimpleNamespace()) is SubsystemLinkState.DOWN


def test_the_state_is_read_off_the_package_every_time_it_is_asked():
    package = SimpleNamespace(link_state=lambda: SubsystemLinkState.DOWN)
    assert link_state_of(package) is SubsystemLinkState.DOWN
    package.link_state = lambda: SubsystemLinkState.UP
    assert link_state_of(package) is SubsystemLinkState.UP
