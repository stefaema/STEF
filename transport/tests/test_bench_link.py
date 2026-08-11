"""What the ladder concludes from each tier, and what it refuses to claim."""

import pytest

from shared import bench_api
from shared.bench_api import StepStatus
from transport import fw_link, fw_probe


@pytest.fixture(scope="module", autouse=True)
def declared():
    """Import the bench package once, the way the backend does."""
    bench_api.load("transport.bench")
    return bench_api.REGISTRY


@pytest.fixture
def verify(declared):
    """Return the routine under test."""
    return declared.bench_test("transport.verify_port")


def candidate(device, vid, description=""):
    """Return one attached port, in the shape pyserial hands them over."""
    return fw_probe.Candidate(device, vid, 1, description, fw_probe._silicon(vid))


@pytest.fixture
def only(monkeypatch):
    """Return a way to say what is attached, with nothing answering on it."""

    def plug(one):
        monkeypatch.setattr(fw_probe, "candidates", lambda: (one,))

        def silent(*_, **__):
            raise fw_link.LinkTimeout("nothing")

        monkeypatch.setattr(fw_probe, "_ask", silent)
        return one

    return plug


def descriptor_step(verify, one):
    """Return how the first rung settled for this port."""
    return next(iter(verify.run(None, port=one.device)))


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
    reached = [o.status for o in verify.run(None, port=one.device)]
    assert len(reached) == 3
    assert reached[0] is StepStatus.WARNED


def test_a_port_that_is_not_attached_stops_the_run_before_anything_is_opened(
    verify, monkeypatch
):
    monkeypatch.setattr(fw_probe, "candidates", lambda: ())
    settled = list(verify.run(None, port="/dev/ttyNOPE"))
    assert settled[0].status is StepStatus.FAILED
    assert [o.status for o in settled[1:]] == [StepStatus.SKIPPED, StepStatus.SKIPPED]
