"""What a bring-up puts on the wire, and how each of its steps settles."""

import pytest

from shared import fw_api
from shared.diagnostics import FAILED, PASSED, SKIPPED, WARNED
from transport import device_profile
from transport.bench import setup
from transport.tests.conftest import Board

BASELINE = "capstan_base"


class Raw:
    """The `raw` namespace, answering without a board and remembering what it was sent."""

    def __init__(self, agrees=True, mismatched=0, conditions=0):
        self.sent = []
        self.agrees = agrees
        self.mismatched = mismatched
        self.conditions = conditions

    def _record(self, name, **values):
        spec = fw_api.namespaces()["raw"][name]
        self.sent.append((name, fw_api.arguments(spec, (), values)))

    def bringup(self, **values):
        self._record("bringup", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_bringup_ret)(gstat_found=1)

    def verify_config(self, **values):
        self._record("verify_config", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_verify_config_ret)(
            mismatched=self.mismatched, agrees=self.agrees
        )

    def poll_health(self, **values):
        self._record("poll_health", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_poll_health_ret)(
            conditions=self.conditions
        )

    def read(self, **values):
        self._record("read", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_read_ret)(value=0x1234)


@pytest.fixture
def raw():
    """Answer every call this routine makes."""
    return Raw()


@pytest.fixture
def declared(linked_to, raw):
    """Return the subsystem, linked to a board that answers through `raw`."""
    return linked_to(Board(raw))


def outcomes(declared, raw, **values):
    """Return every outcome the bring-up yields, in order."""
    found = declared.run_test("setup.BaselineBringup", values, lambda said: None)
    return list(found.outcomes)


def payload_of(raw, name):
    """Return what one call put on the wire."""
    return next(sent for called, sent in raw.sent if called == name)


# ── The run ──────────────────────────────────────────────────────────────────


def test_every_step_settles_and_the_driver_ends_configured(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert [step.status for step in settled[:4]] == [PASSED] * 4
    assert [step.step for step in settled[:4]] == [
        setup.PROFILE,
        setup.BRING_UP,
        setup.READ_BACK,
        setup.HEALTH,
    ]


def test_the_cached_registers_are_read_back_as_one_table(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert settled[4].step == setup.CACHED_REGISTERS
    assert settled[4].result is not None
    assert settled[4].result.table is not None
    assert [row[0] for row in settled[4].result.table.rows] == ["GCONF", "CHOPCONF"]


def test_the_bringup_carries_the_profile_as_the_firmware_frames_it(declared, raw):
    outcomes(declared, raw, idx=1, profile=BASELINE)

    args = fw_api.unpack(fw_api.rpc_raw_write_args, payload_of(raw, "bringup"))
    assert args.idx == 1

    written = {device_profile.register_name(op.reg): op.value for op in args.ops}
    assert written["CHOPCONF"] == device_profile.value_of(
        "chopconf", device_profile.load(BASELINE)["chopconf"]
    )


def test_a_profile_that_does_not_load_stops_the_run_before_the_wire(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile="nothing_installed")

    assert settled[0].status is FAILED
    assert [step.status for step in settled[1:]] == [SKIPPED] * 4
    assert raw.sent == []


def test_a_driver_holding_something_else_fails_the_read_back(declared, raw):
    raw.agrees = False
    raw.mismatched = 1 << fw_api.tmc2209_reg_slot(fw_api.TMC2209_GCONF)

    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert settled[2].status is FAILED
    assert "GCONF" in settled[2].detail
    assert settled[3].status is SKIPPED


def test_a_condition_is_reported_and_never_fails_the_run(declared, raw):
    raw.conditions = int(fw_api.TMC2209_OVERTEMP_WARNING)

    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert settled[3].status is WARNED
    assert "OVERTEMP_WARNING" in settled[3].detail
    assert len(settled) > 4


# ── Stopping everything ──────────────────────────────────────────────────────


class Stoppable:
    def __init__(self, refuses=()):
        self.sent = []
        self.refuses = refuses
        self.on = {}

    def halt(self, idx, immediate):
        self.sent.append(("halt", idx, immediate))
        if ("halt", idx, immediate) in self.refuses:
            raise TimeoutError("no reply")

    def set_velocity(self, idx, velocity):
        self.sent.append(("set_velocity", idx, velocity))

    def enable(self, idx, on):
        self.sent.append(("enable", idx, on))
        self.on[idx] = on and ("stuck", idx) not in self.refuses
        if ("stuck", idx) in self.refuses:
            self.on[idx] = True

    def is_enabled(self, idx):
        return type("Enabled", (), {"on": self.on.get(idx, False)})()


def test_stopping_halts_zeroes_and_releases_every_drive(linked_to):
    raw = Stoppable()
    sub = linked_to(Board(raw, names=("capstan", "takeup")))

    sub.stop()

    assert raw.sent == [
        ("halt", 0, False),
        ("set_velocity", 0, 0),
        ("enable", 0, False),
        ("halt", 1, False),
        ("set_velocity", 1, 0),
        ("enable", 1, False),
    ]


def test_a_ramp_that_is_refused_falls_back_to_an_immediate_halt(linked_to):
    raw = Stoppable(refuses=(("halt", 0, False),))
    sub = linked_to(Board(raw))

    sub.stop()

    assert ("halt", 0, True) in raw.sent


def test_a_drive_that_will_not_release_is_named_after_every_drive_was_tried(
    linked_to,
):
    raw = Stoppable(refuses=(("stuck", 0),))
    sub = linked_to(Board(raw, names=("capstan", "takeup")))

    with pytest.raises(RuntimeError, match="capstan: RuntimeError"):
        sub.stop()

    assert ("enable", 1, False) in raw.sent
