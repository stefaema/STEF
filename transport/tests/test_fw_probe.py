"""What a descriptor is worth, and what asking the firmware settles on top of it."""

import pytest

from shared import fw_api
from transport import fw, transport

# ── The descriptor tier ──────────────────────────────────────────────────────


def port(device, vid, pid=0x0001, description="a thing"):
    """Return one fake attached port, in the shape pyserial hands them over."""
    return fw.probe.Candidate(
        device=device,
        vid=vid,
        pid=pid,
        description=description,
        silicon=fw.probe._silicon(vid),
    )


@pytest.fixture
def attached(monkeypatch):
    """Return a way to say what is plugged in for the length of one test."""

    def plug(*ports):
        monkeypatch.setattr(fw.probe, "candidates", lambda: tuple(ports))
        return ports

    return plug


def test_espressifs_own_vendor_id_settles_the_silicon():
    assert port("/dev/ttyACM0", 0x303A).silicon is fw.probe.Silicon.ESPRESSIF


def test_a_bridge_vendor_is_a_shortlist_and_not_an_answer():
    bridge = port("/dev/ttyUSB0", 0x10C4)
    assert bridge.silicon is fw.probe.Silicon.BRIDGE
    assert bridge.plausible


def test_an_unknown_vendor_is_not_worth_talking_to():
    assert not port("/dev/ttyS0", 0x1D6B).plausible


def test_the_shortlist_leaves_out_what_could_not_carry_a_board(attached):
    attached(port("/dev/ttyACM0", 0x303A), port("/dev/ttyS0", None))
    assert fw.probe.plausible_ports() == ("/dev/ttyACM0",)


def test_one_shortlisted_port_is_the_answer_when_none_was_named(attached):
    attached(port("/dev/ttyACM0", 0x303A), port("/dev/ttyS0", None))
    assert fw.probe.find_port() == "/dev/ttyACM0"


def test_several_shortlisted_ports_is_a_question_and_not_an_answer(attached):
    attached(port("/dev/ttyACM0", 0x303A), port("/dev/ttyUSB0", 0x1A86))
    with pytest.raises(fw.link.LinkError, match="name one"):
        fw.probe.find_port()


def test_a_named_port_is_taken_even_where_its_descriptor_says_nothing(attached):
    attached(port("/dev/ttyS4", None))
    assert fw.probe.find_port("/dev/ttyS4") == "/dev/ttyS4"


def test_a_named_port_that_has_gone_is_refused_rather_than_opened(attached):
    attached(port("/dev/ttyACM0", 0x303A))
    with pytest.raises(fw.link.LinkError, match="nothing is attached"):
        fw.probe.find_port("/dev/ttyUSB9")


# ── What an operator may choose ──────────────────────────────────────────────


def test_every_attached_port_is_offered_and_not_only_the_shortlist(attached):
    attached(port("/dev/ttyS0", None), port("/dev/ttyACM0", 0x303A))
    offered = [value for value, _ in transport.serial_ports()]
    assert offered == [transport.AUTO, "/dev/ttyACM0", "/dev/ttyS0"]


def test_the_likely_ports_sort_first_so_the_list_reads_as_a_recommendation(attached):
    attached(
        port("/dev/ttyS0", None), port("/dev/ttyS1", None), port("/dev/ttyUSB0", 0x1A86)
    )
    offered = [value for value, _ in transport.serial_ports()]
    assert offered[1] == "/dev/ttyUSB0"


def test_a_port_worth_trying_says_what_it_looks_like(attached):
    attached(port("/dev/ttyACM0", 0x303A, description="USB JTAG/serial debug unit"))
    labels = dict(transport.serial_ports())
    assert labels["/dev/ttyACM0"] == "/dev/ttyACM0 (USB JTAG/serial debug unit)"


def test_a_port_that_is_probably_something_else_is_offered_without_a_claim(attached):
    attached(port("/dev/ttyS0", None, description="16550A"))
    assert dict(transport.serial_ports())["/dev/ttyS0"] == "/dev/ttyS0"


# ── The app tier ─────────────────────────────────────────────────────────────


class Reply:
    """What `sys.version` answers, without a board to answer it."""

    def __init__(self, version=b"0.3.1", protocol=None, project=b"stef-fw"):
        self.protocol = fw_api.RPC_PROTOCOL_VERSION if protocol is None else protocol
        self.reset_reason = 1
        self.project = project
        self.version = version
        self.idf = b"v5.2"


@pytest.fixture
def answering(monkeypatch, attached):
    """Return a way to say what the firmware on a port replies, or that none does."""

    def speak(reply):
        attached(port("/dev/ttyACM0", 0x303A))

        def ask(_port, _grace):
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(fw.probe, "_ask", ask)

    return speak


def test_the_pinned_version_answering_is_the_only_finding_that_is_ok(answering):
    answering(Reply(version=b"0.3.1"))
    verdict = fw.probe.identify("/dev/ttyACM0", "0.3.1")
    assert verdict.finding is fw.probe.Finding.RUNNING
    assert verdict
    assert verdict.version == "0.3.1"


def test_another_version_answering_names_both_of_them(answering):
    answering(Reply(version=b"0.2.9"))
    verdict = fw.probe.identify("/dev/ttyACM0", "0.3.1")
    assert verdict.finding is fw.probe.Finding.STALE
    assert not verdict
    assert "0.2.9" in verdict.sentence and "0.3.1" in verdict.sentence


def test_a_protocol_disagreement_is_told_apart_from_a_stale_build(answering):
    answering(Reply(version=b"0.3.1", protocol=fw_api.RPC_PROTOCOL_VERSION + 7))
    verdict = fw.probe.identify("/dev/ttyACM0", "0.3.1")
    assert verdict.finding is fw.probe.Finding.PROTOCOL


def test_without_a_pin_the_running_version_is_reported_and_not_judged(answering):
    answering(Reply(version=b"0.2.9"))
    verdict = fw.probe.identify("/dev/ttyACM0", None)
    assert verdict.finding is fw.probe.Finding.RUNNING
    assert "no version is pinned" in verdict.sentence


def test_a_fixed_width_string_is_read_up_to_its_terminator(answering):
    answering(Reply(version=b"0.3.1\x00\x00\x00\x00"))
    assert fw.probe.identify("/dev/ttyACM0", "0.3.1").version == "0.3.1"


def test_silence_carries_the_silicon_so_the_advice_can_differ(answering):
    answering(fw.link.LinkTimeout("nothing"))
    verdict = fw.probe.identify("/dev/ttyACM0", "0.3.1")
    assert verdict.finding is fw.probe.Finding.SILENT
    assert verdict.silicon is fw.probe.Silicon.ESPRESSIF
    assert "held in reset" in verdict.sentence


def test_a_port_that_will_not_open_is_not_the_same_as_one_that_says_nothing(answering):
    answering(PermissionError("busy"))
    verdict = fw.probe.identify("/dev/ttyACM0", "0.3.1")
    assert verdict.finding is fw.probe.Finding.ABSENT
    assert "would not open" in verdict.sentence


def test_a_port_that_has_gone_is_settled_before_anything_is_opened(attached):
    attached()
    assert fw.probe.identify("/dev/ttyACM0").finding is fw.probe.Finding.ABSENT
