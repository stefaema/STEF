"""What the ladder concludes from each tier, and what it refuses to claim."""

import pytest

from shared import bench_api
from shared.bench_api import StepStatus
from transport import fw, transport
from transport.bench import link


@pytest.fixture
def verify(declared):
    """Return the routine under test."""
    return declared.routines["prelink.verify_port"]


def candidate(device, vid, description=""):
    """Return one attached port, in the shape pyserial hands them over."""
    return fw.probe.Candidate(device, vid, 1, description, fw.probe._silicon(vid))


@pytest.fixture
def attached(monkeypatch):
    """Return a way to say what is plugged in for the length of one test."""

    def plug(*ports):
        monkeypatch.setattr(fw.probe, "candidates", lambda: tuple(ports))
        return ports

    return plug


@pytest.fixture
def only(monkeypatch):
    """Return a way to say what is attached, with nothing answering on it."""

    def plug(one):
        monkeypatch.setattr(fw.probe, "candidates", lambda: (one,))

        def silent(*_, **__):
            raise fw.link.LinkTimeout("nothing")

        monkeypatch.setattr(fw.probe, "_ask", silent)
        return one

    return plug


def descriptor_step(verify, one):
    """Return how the first rung settled for this port."""
    return next(iter(bench_api.run_routine(verify, {"port": one.device})))


def test_espressif_silicon_is_the_one_thing_a_descriptor_settles(verify, only):
    one = only(candidate("/dev/ttyACM0", 0x303A, "USB JTAG/serial debug unit"))
    settled = descriptor_step(verify, one)
    assert settled.status is StepStatus.PASSED
    assert "Espressif silicon" in settled.detail


def test_a_bridge_passes_without_claiming_anything_about_what_is_behind_it(
    verify, only
):
    one = only(candidate("/dev/ttyUSB0", 0x10C4, "CP2102 UART Bridge"))
    settled = descriptor_step(verify, one)
    assert settled.status is StepStatus.PASSED
    assert settled.value is not None
    assert "never what is behind it" in (settled.value.note or "")


def test_a_port_the_descriptor_does_not_recognise_is_not_a_pass(verify, only):
    one = only(candidate("/dev/ttyS1", None, "n/a"))
    settled = descriptor_step(verify, one)
    assert settled.status is StepStatus.WARNED
    assert "does not look like a board" in settled.detail


def test_an_unrecognised_port_is_still_asked_rather_than_refused(verify, only):
    one = only(candidate("/dev/ttyS1", None, "n/a"))
    reached = [o.status for o in bench_api.run_routine(verify, {"port": one.device})]
    assert len(reached) == 3
    assert reached[0] is StepStatus.WARNED


def test_a_port_that_is_not_attached_stops_the_run_before_anything_is_opened(
    verify, monkeypatch
):
    monkeypatch.setattr(fw.probe, "candidates", lambda: ())
    settled = list(bench_api.run_routine(verify, {"port": "/dev/ttyNOPE"}))
    assert settled[0].status is StepStatus.FAILED
    assert [o.status for o in settled[1:]] == [StepStatus.SKIPPED, StepStatus.SKIPPED]


# ── What an operator may choose ──────────────────────────────────────────────


def test_every_attached_port_is_offered_and_not_only_the_shortlist(attached):
    attached(candidate("/dev/ttyS0", None), candidate("/dev/ttyACM0", 0x303A))
    offered = [value for value, _ in link.serial_ports()]
    assert offered == [transport.AUTO, "/dev/ttyACM0", "/dev/ttyS0"]


def test_the_likely_ports_sort_first_so_the_list_reads_as_a_recommendation(attached):
    attached(
        candidate("/dev/ttyS0", None),
        candidate("/dev/ttyS1", None),
        candidate("/dev/ttyUSB0", 0x1A86),
    )
    offered = [value for value, _ in link.serial_ports()]
    assert offered[1] == "/dev/ttyUSB0"


def test_a_port_worth_trying_says_what_it_looks_like(attached):
    attached(candidate("/dev/ttyACM0", 0x303A, "USB JTAG/serial debug unit"))
    labels = dict(link.serial_ports())
    assert labels["/dev/ttyACM0"] == "/dev/ttyACM0 (USB JTAG/serial debug unit)"


def test_a_port_that_is_probably_something_else_is_offered_without_a_claim(attached):
    attached(candidate("/dev/ttyS0", None, "16550A"))
    assert dict(link.serial_ports())["/dev/ttyS0"] == "/dev/ttyS0"
