"""What a package reports when asked for its state."""

from types import SimpleNamespace

from shared.subsystem import SubsystemState, state_of


def test_a_package_reporting_nothing_is_down():
    assert state_of(SimpleNamespace()) is SubsystemState.DOWN


def test_the_state_is_read_off_the_package_every_time_it_is_asked():
    package = SimpleNamespace(state=lambda: SubsystemState.DOWN)
    assert state_of(package) is SubsystemState.DOWN
    package.state = lambda: SubsystemState.UP
    assert state_of(package) is SubsystemState.UP
