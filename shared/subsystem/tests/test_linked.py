import threading
import types

import pytest

from shared.subsystem import (
    READY,
    Linked,
    LinkState,
    NotLinked,
    NotReady,
    Subsystem,
    blocked,
    choice,
)

PACKAGE = types.ModuleType("shared.oven", "The oven.\n\nOne element and its probe.")


class Port:
    def __init__(self, name):
        self.name = name
        self.alive = True
        self.closed = False


class Oven(Linked[str]):
    target = choice("port", ("/dev/oven0",))

    def __init__(self, package=PACKAGE):
        super().__init__(package)
        self.refusal: str | None = None
        self.fails_to_open: Exception | None = None
        self.stops: list[LinkState] = []
        self.fails_to_stop: Exception | None = None
        self.gate: threading.Event | None = None

    def probe(self, target):
        if self.gate is not None:
            self.gate.wait(5)
        return blocked(self.refusal) if self.refusal else READY

    def _open(self, target):
        if self.fails_to_open:
            raise self.fails_to_open
        return Port(target)

    def _close(self, handle):
        handle.closed = True

    def _alive(self, handle):
        return handle.alive

    def stop(self):
        self.stops.append(self.link_state())
        if self.fails_to_stop:
            raise self.fails_to_stop


def test_identity_is_read_off_the_package():
    oven = Subsystem(PACKAGE)

    assert (oven.id, oven.summary, oven.description) == (
        "oven",
        "The oven.",
        "One element and its probe.",
    )
    assert oven.config.package == "shared.oven"


def test_a_subsystem_with_no_link_is_down():
    assert Subsystem(PACKAGE).link_state() is LinkState.DOWN


def test_connecting_opens_the_target_and_the_link_is_up():
    oven = Oven()

    oven.connect("/dev/oven0")

    assert oven.link_state() is LinkState.UP
    assert oven.handle().name == "/dev/oven0"


def test_a_probe_that_refuses_keeps_the_link_down():
    oven = Oven()
    oven.refusal = "nothing answers on /dev/oven0"

    with pytest.raises(NotReady, match="nothing answers"):
        oven.connect("/dev/oven0")

    assert oven.link_state() is LinkState.DOWN


def test_a_failed_open_is_an_error_with_the_exception_as_reason():
    oven = Oven()
    oven.fails_to_open = OSError("busy")

    with pytest.raises(OSError):
        oven.connect("/dev/oven0")

    assert oven.link_state() is LinkState.ERROR
    assert oven.link_reason() == "OSError: busy"


def test_connecting_twice_is_refused():
    oven = Oven()
    oven.connect("/dev/oven0")

    with pytest.raises(NotReady, match="already connected"):
        oven.connect("/dev/oven0")


def test_a_second_connect_while_the_first_is_probing_is_refused():
    oven = Oven()
    gate = oven.gate = threading.Event()
    first = threading.Thread(target=oven.connect, args=("/dev/oven0",))
    first.start()
    while oven.link_state() is not LinkState.LINKING:
        pass

    with pytest.raises(NotReady, match="already connecting"):
        oven.connect("/dev/oven0")

    gate.set()
    first.join()
    assert oven.link_state() is LinkState.UP


def test_a_handle_that_stopped_answering_is_an_error():
    oven = Oven()
    oven.connect("/dev/oven0")

    oven.handle().alive = False

    assert oven.link_state() is LinkState.ERROR
    assert oven.link_reason() == "the connection stopped answering"


def test_connecting_after_the_link_died_replaces_the_dead_handle():
    oven = Oven()
    oven.connect("/dev/oven0")
    dead = oven.handle()
    dead.alive = False

    oven.connect("/dev/oven0")

    assert dead.closed
    assert oven.link_state() is LinkState.UP


def test_disconnecting_stops_while_up_then_closes():
    oven = Oven()
    oven.connect("/dev/oven0")
    port = oven.handle()

    oven.disconnect()

    assert oven.stops == [LinkState.UP]
    assert port.closed
    assert oven.link_state() is LinkState.DOWN


def test_disconnecting_closes_even_when_stopping_fails():
    oven = Oven()
    oven.connect("/dev/oven0")
    port = oven.handle()
    oven.fails_to_stop = RuntimeError("element 1 did not confirm")

    with pytest.raises(RuntimeError, match="element 1"):
        oven.disconnect()

    assert port.closed
    assert oven.link_state() is LinkState.DOWN


def test_a_link_that_is_down_has_no_handle():
    with pytest.raises(NotLinked):
        Oven().handle()
