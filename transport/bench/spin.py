"""One turn of a motor, and everything the driver will say about it.

A move that goes wrong on the bench goes wrong for one of three reasons: a wire
is not there, the driver is not configured, or the pulse train is not what was
asked for. A motion report cannot tell them apart, because the firmware counts
the edges it emitted whether or not anything received them.

So the interesting answers here are comparisons between two sources rather than
readings from one. What the ESP32 drives on a pin against what the driver sees
on that same pin. The rate that was commanded against the rate the driver
measured between microsteps. The address the board declares against the one the
straps actually select. Each pair agrees or it names the wire that does not.

Two routines, and the pair is the instrument. `one_turn` moves the shaft the way
the machine will: a counted pulse train out of the ESP32 and down a wire.
`velocity_turn` moves it from the driver's own velocity register over the UART
that configured it, with the STEP pin, its wire, the RMT channel and the ramp
all out of the circuit. A driver that turns under one and not the other has
named which half is at fault, and neither result alone can do that.

Eighteen of the firmware's twenty-two `raw` methods run across the two. Left out
are `write` and `invalidate_owned`, which would undo the bring-up both depend on,
`line_write`, which would fight `enable` for the ENN pin, and `retarget`, which
would move the finish line mid-turn and leave the timing proving nothing.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from typing import Any

from shared import bench_api, fw_api
from shared.bench_api import (
    FAILED,
    PASSED,
    WARNED,
    Abandoned,
    Level,
    Result,
    StepOutcome,
    Table,
)
from transport import device_profile, transport
from transport.bench.calls import DEVICE, devices
from transport.bench.setup import flag_rows, hex_word, named_conditions

IDENTIFY = "Identify"
DISABLE = "Disable"
BRING_UP = "Bring-up"
CURRENT = "Current"
PLAN = "Plan"
PROBE = "Probe"
ENABLE = "Enable"
MOVE = "Move"
MIDWAY = "Midway"
DIAGNOSE = "Diagnose"
SETTLED = "Settled"
REST = "At rest"

# What a 1.8 degree motor takes to come round, which is every stepper this bench
# has seen. A 0.9 degree part turns half as far and the report will say so.
FULL_STEPS_PER_TURN = 200

# Long enough to watch a flag go round and read the midway report off the
# screen while it is still true.
TURN_SECONDS = 2.0

# A ramp is expressed against the cruise rate rather than in absolute terms, so
# one holds for any speed: accel is four times cruise, pull-in a quarter of it.
# Both ramps then last (1 - 1/4) / 4 = 0.1875 s whatever the rate works out to.
RAMP_STEEPNESS = 4
PULLIN_SHARE = 4

# A ramp covers fewer pulses per second than cruising does, so the two of them
# cost the turn this much time beyond what pulses / cruise_pps predicts.
RAMP_OVERHEAD_S = 2 * (
    (1 - 1 / PULLIN_SHARE) / RAMP_STEEPNESS
    - (1 - 1 / PULLIN_SHARE**2) / (2 * RAMP_STEEPNESS)
)

# A flag printed in PLA is not a load. 0.5 A RMS turns it and keeps the motor
# cold enough to leave running, against the 0.94 A the baseline profile asks for.
#
#   IRMS = (CS + 1) / 32 * 0.325 / (0.11 + 0.02) / sqrt(2)
SPIN_IHOLD = 4
SPIN_IRUN = 8
SPIN_IHOLDDELAY = 8

# Grace beyond the calculated turn, for the report to catch the last pulse.
SETTLE_MARGIN_S = 0.5

# The slowest rate the backend encodes is 16 pps. A little above it, one pulse
# is 25 ms high and 25 ms low, against an RPC round trip of roughly 12 ms: slow
# enough to sample over the link, fast enough not to hold the routine up.
PROBE_PPS = 20
PROBE_SECONDS = 2.0

# Below this share of samples on one side, a bit that changed did so by accident.
PROBE_MINORITY = 0.1

# Long enough under VACTUAL to see whether it settles rather than only starts.
VELOCITY_SECONDS = 3.0

# One VACTUAL unit is one microstep per this many clocks, at whatever resolution
# CHOPCONF holds. Unlike TSTEP it is not normalised to 1/256 of a fullstep.
VACTUAL_PERIOD = 2**24

# 20000 is around 270 RPM at 16 microsteps, already far past where a motor given
# no ramp stops keeping up, so there is nothing above it worth offering.
VELOCITY_MAX = 20_000

# The internal oscillator TSTEP is counted against. Trimmed at the factory to
# within 15%, which is the accuracy any rate derived from TSTEP inherits.
FCLK_HZ = 12_000_000
FCLK_TOLERANCE = 0.15

# The revision byte every TMC2209 answers with in IOIN.
TMC2209_VERSION = 0x21

# The one live register per named thing worth watching mid-turn. MSCNT is not
# here because it is read twice, before and after, and the difference is the
# reading rather than either sample.
WATCHED = (
    fw_api.TMC2209_DRV_STATUS,
    fw_api.TMC2209_MSCURACT,
    fw_api.TMC2209_PWM_SCALE,
)

# The microstep counter wraps over one electrical revolution, which is four full
# steps however many microsteps each is divided into.
MSCNT_WRAP = 1024
FULL_STEPS_PER_ELECTRICAL_TURN = 4

# What a driver reports standing still: no current in the coils reads as an open
# load, and stillness is itself a flag.
AT_REST = fw_api.TMC2209_STANDSTILL | fw_api.TMC2209_OPEN_LOAD

# The two that survive until something acknowledges them, so a stale one from an
# earlier session would otherwise be reported as this run's.
LATCHED = fw_api.TMC2209_DRIVER_RESET | fw_api.TMC2209_DRIVER_FAULT

# Only the two the ESP32 drives and the driver receives. Comparing the ends of a
# line is a wiring test when the signal travels one way and nothing more than a
# curiosity when it does not: DIAG is the driver's output and STEP belongs to the
# pulse source, so both are reported from the driver's end alone and neither is
# ever held against the board.
LINES = (
    fw_api.TMC2209_LINE_ENN,
    fw_api.TMC2209_LINE_DIR,
)


def _line_name(line: int) -> str:
    """Return one line's name as the datasheet prints it."""
    return fw_api.Tmc2209Line(line).name.removeprefix("TMC2209_LINE_")


def _driven(raw: Any, idx: int) -> dict[str, bool | None]:
    """Return what the ESP32 has on each of this driver's pins.

    A line the board does not wire is refused rather than guessed, and a board
    that wires three of the four is a board this should still report on. So a
    refusal is None here and a row that says so later, never an ended run.
    """
    found: dict[str, bool | None] = {}
    for line in LINES:
        try:
            found[_line_name(line).lower()] = bool(
                raw.line_read(idx=idx, line=int(line)).level
            )
        except Exception:  # noqa: BLE001
            found[_line_name(line).lower()] = None
    return found


def _seen(raw: Any, idx: int) -> Any:
    """Return what the driver reports on its own pins, decoded."""
    return fw_api.tmc2209_ioin_decode(raw.poll_pins(idx=idx).value)


def _pin_rows(driven: Mapping[str, bool | None], seen: Any) -> Table:
    """Return the two ends of every shared pin side by side, and whether they agree.

    STEP gets a row of its own with only the driver's end filled in, since that
    is the one end anybody may read while a pulse source owns the pad.
    """
    rows = [
        (
            name.upper(),
            "refused" if ours is None else "high" if ours else "low",
            "high" if theirs else "low",
            "-" if ours is None else "yes" if bool(ours) == bool(theirs) else "NO",
        )
        for name, ours in driven.items()
        for theirs in (getattr(seen, name),)
    ]
    rows.append(("STEP", "owned by the stepgen", "high" if seen.step else "low", "-"))
    rows.append(("DIAG", "driven by the driver", "high" if seen.diag else "low", "-"))
    return Table(
        head=("line", "esp32 drives", "driver sees", "agrees"), rows=tuple(rows)
    )


def _disagreeing(driven: Mapping[str, bool | None], seen: Any) -> tuple[str, ...]:
    """Return the lines whose two ends do not hold the same level."""
    return tuple(
        name.upper()
        for name, ours in driven.items()
        if ours is not None and bool(ours) != bool(getattr(seen, name))
    )


def _strapped(seen: Any) -> int:
    """Return the address the MS1 and MS2 straps select, MS1 being the low bit."""
    return (1 if seen.ms1 else 0) | (2 if seen.ms2 else 0)


def _declared_address(idx: int) -> int | None:
    """Return the address the board table gives this driver, or None if it cannot say."""
    try:
        return int(transport.firmware().sys.devices().devs[idx].addr)
    except Exception:  # noqa: BLE001
        return None


def _measured_pps(tstep: int, microsteps: int) -> float | None:
    """Return the rate the driver timed between microsteps, in pulses per second.

    TSTEP counts in 1/fCLK the interval between two 1/256 microsteps, not between
    two STEP pulses. One pulse advances the internal table by 256/microsteps of
    those, so the pulse rate is that many times slower than TSTEP alone implies.
    A driver that is standing still, or too slow to time, reads all ones.
    """
    if tstep <= 0 or tstep >= 0xFFFFF:
        return None
    return FCLK_HZ * microsteps / (256 * tstep)


def _plan(microsteps: int) -> dict[str, int]:
    """Return the run that turns the shaft once in about TURN_SECONDS."""
    pulses = FULL_STEPS_PER_TURN * microsteps
    cruise = round(pulses / (TURN_SECONDS - RAMP_OVERHEAD_S))
    return {
        "pulses": pulses,
        "cruise_pps": cruise,
        "pullin_pps": max(1, cruise // PULLIN_SHARE),
        "accel_pps_s": cruise * RAMP_STEEPNESS,
    }


def _velocity_pps(vactual: int) -> float:
    """Return what a VACTUAL setting asks for, as the STEP pulses per second it stands in for.

    VACTUAL counts microsteps at the resolution CHOPCONF is holding, one per
    2^24 / fCLK, so it is already in the units a pulse would have been and takes
    no factor for the microstep count. TSTEP is the one that is normalised to
    1/256 of a fullstep and needs converting, which is the opposite of what the
    two register descriptions read like at a glance.
    """
    return abs(vactual) * FCLK_HZ / VACTUAL_PERIOD


def _counter_pps(raw: Any, idx: int, per_pulse: int) -> tuple[float | None, int]:
    """Return the rate the microstep counter is advancing at, timed from here.

    A third account of the same motion, owing nothing to TSTEP or to VACTUAL: two
    reads of MSCNT with nothing between them, divided by the wall clock. It is
    coarse, since an RPC round trip is in the interval, and it aliases once the
    counter laps between the two reads, which the comparison with TSTEP is what
    catches.
    """
    first = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
    started = time.monotonic()
    second = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
    gap = time.monotonic() - started

    advanced = (second - first) % MSCNT_WRAP
    if gap <= 0 or per_pulse <= 0:
        return None, advanced
    return advanced / gap / per_pulse, advanced


def _rpm(pps: float, microsteps: int) -> float:
    """Return a pulse rate as shaft revolutions per minute."""
    return pps * 60 / (microsteps * FULL_STEPS_PER_TURN)


def _step_wire_probe(raw: Any, idx: int) -> tuple[int, int, int, int]:
    """Return how the driver's own STEP pin behaved while the firmware pulsed it.

    The pulse counter watches the pad the ESP32 drives, so a count proves the
    train exists and never that it arrived. IOIN reports the level on the
    driver's STEP pin, which is the far end of the wire, and is the only thing
    on this link that can answer that.

    It only works slowly. At a rate worth turning at, the pin is high for a few
    hundred microseconds in every few hundred more, and a poll with milliseconds
    of latency samples it almost anywhere. At 20 pps the pin holds each state for
    25 ms, which nothing here can miss.

    Runs unbounded and is cut immediately, so it costs the pulses it emits and
    no distance the caller has to account for. Whoever calls this owns leaving
    the power stage off: nothing below turns anything, and nothing above should.
    """
    raw.set_velocity(idx=idx, velocity=0)
    raw.move(
        idx=idx,
        dir=False,
        shaft=False,
        pulses=0,
        pullin_pps=PROBE_PPS,
        cruise_pps=PROBE_PPS,
        accel_pps_s=0,
    )

    levels: list[bool] = []
    deadline = time.monotonic() + PROBE_SECONDS
    while time.monotonic() < deadline:
        levels.append(bool(_seen(raw, idx).step))

    raw.halt(idx=idx, immediate=True)
    emitted = raw.motion_report(idx=idx).emitted

    high = sum(1 for level in levels if level)
    changes = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
    return len(levels), high, changes, emitted


def _report_table(report: Any, commanded: int, elapsed: float) -> Table:
    """Return a motion report as its own fields, then what they imply together.

    The report carries five numbers and each is only half an answer. A count
    means little without the count that was asked for, and a rate means little
    without the rate it was aimed at. The lower rows are those pairings, and the
    average is the one figure the report cannot hold: emitted over the PC's own
    elapsed time, which is a third clock after the ESP32's and the driver's.
    """
    rows = [
        ("emitted", f"{report.emitted} of {commanded}"),
        ("rate_pps", str(report.rate_pps)),
        ("running", "yes" if report.running else "no"),
        ("dir", "high" if report.dir else "low"),
        ("shaft", "true" if report.shaft else "false"),
        ("turned", f"{report.emitted / commanded:.1%}" if commanded else "unbounded"),
        ("still owed", str(max(0, commanded - report.emitted))),
        ("elapsed", f"{elapsed:.2f} s"),
    ]
    if elapsed > 0:
        rows.append(("average so far", f"{report.emitted / elapsed:.0f} pps"))
    return Table(head=("motion report", "value"), rows=tuple(rows))


def _health(raw: Any, idx: int) -> fw_api.Tmc2209Condition:
    """Return what the driver reports about itself, as the flag set it stands for."""
    return fw_api.Tmc2209Condition(raw.poll_health(idx=idx).conditions)


@bench_api.routine(
    hazardous=True,
    steps=[
        IDENTIFY,
        DISABLE,
        BRING_UP,
        CURRENT,
        PLAN,
        PROBE,
        ENABLE,
        MOVE,
        MIDWAY,
        DIAGNOSE,
        SETTLED,
        REST,
    ],
    inputs=[
        bench_api.choice("idx", devices, hint=DEVICE),
        bench_api.choice(
            "profile",
            device_profile.names,
            hint="Which profile to bring the driver up on before it turns.",
        ),
        bench_api.boolean(
            "dir",
            hint="The level to drive on DIR. Electrical, so which way it turns "
            "depends on how the coils are wired.",
        ),
    ],
)
def one_turn(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Turn a shaft once and read the driver at every stage.

    Brings a driver up, turns it exactly one revolution in about two seconds at
    a current low enough for a printed flag and no other load, and reports the
    move twice: once halfway through while it is still running, and once after
    it has stopped.

    The revolution is derived, not assumed. Microsteps come from the CHOPCONF
    the driver is actually holding, so a profile at a different resolution turns
    the same distance at the same speed and simply emits more pulses.

    Everything here is a comparison. The lines are read from both ends, the
    strapped address is checked against the one the board declares, and the
    commanded rate is checked against the rate the driver timed for itself.
    """
    raw = transport.firmware().raw
    idx = values["idx"]
    profile = values["profile"]
    direction = bool(values["dir"])

    # ── Who is on the other end ──────────────────────────────────────────────

    version = raw.poll_version(idx=idx).version
    seen = _seen(raw, idx)
    strapped = _strapped(seen)
    declared = _declared_address(idx)

    if version != TMC2209_VERSION:
        raise Abandoned(
            f"the part answered version 0x{version:02x}, and a TMC2209 answers "
            f"0x{TMC2209_VERSION:02x}",
            FAILED,
            Result(
                level=Level.ERROR,
                summary=f"version 0x{version:02x} is not a TMC2209",
                note="Either something else is on this address or the reply was "
                "corrupted on the way back.",
            ),
        )

    mismatched_address = declared is not None and declared != strapped
    yield StepOutcome(
        WARNED if mismatched_address else PASSED,
        f"a TMC2209 answers here, strapped to address {strapped}"
        + (f", and the board declares {declared}" if mismatched_address else ""),
        Result(
            level=Level.WARN if mismatched_address else Level.OK,
            summary=f"version 0x{version:02x}, address {strapped} by the straps",
            note="MS1 is the low bit of the address and MS2 the high one. A "
            "driver that answered at all is already strapped to the address it "
            "was asked at, so a disagreement here means the reply came from "
            "somewhere unexpected.",
            fields=flag_rows(seen),
        ),
        step=IDENTIFY,
    )

    # ── Off before anything else happens ─────────────────────────────────────

    raw.enable(idx=idx, on=False)
    off = raw.is_enabled(idx=idx).on
    driven = _driven(raw, idx)
    seen = _seen(raw, idx)
    disagreeing = _disagreeing(driven, seen)

    if off:
        raise Abandoned(
            "the driver still reports its power stage enabled after being told off",
            FAILED,
        )
    differing = ", ".join(disagreeing)
    yield StepOutcome(
        WARNED if disagreeing else PASSED,
        f"power stage off, and {differing} reads differently at each end"
        if disagreeing
        else "power stage off, every line reading the same at both ends",
        Result(
            level=Level.WARN if disagreeing else Level.OK,
            summary="ENN high and the stage is off"
            if not disagreeing
            else f"{differing} does not carry between the ESP32 and the driver",
            note="ENN is active low, so high is off. The two columns are the "
            "same physical pin read from the ESP32 and from the driver: they "
            "disagree only when the wire between them does not carry.",
            table=_pin_rows(driven, seen),
        ),
        step=DISABLE,
    )

    # ── The configuration it will turn on ────────────────────────────────────

    try:
        ops = device_profile.ops(device_profile.load(profile))
    except Exception as exc:
        raise Abandoned(
            f"{profile} is not a configuration this driver can be given: {exc}", FAILED
        ) from exc

    found = raw.bringup(idx=idx, ops=list(ops))
    agreed = raw.verify_config(idx=idx)
    valid = raw.all_owned_valid(idx=idx).valid

    if not agreed.agrees:
        differing = ", ".join(device_profile.slot_names(agreed.mismatched))
        raise Abandoned(
            f"the driver disagrees with what was written: {differing or 'no register named'}",
            FAILED,
            Result(
                level=Level.ERROR,
                summary="the driver holds something else",
                fields=(("mismatched", hex_word(agreed.mismatched)),),
            ),
        )
    yield StepOutcome(
        PASSED if valid else WARNED,
        f"{profile} is on the driver, GSTAT was "
        f"{hex_word(found.gstat_at_bringup)} when it was claimed",
        Result(
            level=Level.OK if valid else Level.WARN,
            summary=f"{len(ops)} owned registers written and agreed",
            note="GSTAT as found is the only look anyone gets at what the driver "
            "went through before this firmware owned it.",
            fields=(("all_owned_valid", "true" if valid else "false"),)
            + flag_rows(fw_api.tmc2209_gstat_decode(found.gstat_at_bringup)),
        ),
        step=BRING_UP,
    )

    standing = _health(raw, idx)
    latched = standing & LATCHED
    if latched:
        raw.clear_faults(idx=idx, conditions=int(latched))
        standing = _health(raw, idx)

    # ── A current a printed flag can be turned with ──────────────────────────

    raw.set_current(
        idx=idx, ihold=SPIN_IHOLD, irun=SPIN_IRUN, iholddelay=SPIN_IHOLDDELAY
    )
    yield StepOutcome(
        PASSED,
        f"run current set to CS {SPIN_IRUN}, hold to CS {SPIN_IHOLD}",
        Result(
            level=Level.OK,
            summary=f"IRUN {SPIN_IRUN}, IHOLD {SPIN_IHOLD}, IHOLDDELAY "
            f"{SPIN_IHOLDDELAY}",
            note="About 0.50 A RMS running on 0.11 ohm sense resistors with "
            "vsense off. IHOLD_IRUN is write-only on the part, so this is what "
            "was sent rather than what was read back.",
            fields=(
                ("conditions after bring-up", named_conditions(standing) or "none"),
                ("cleared", named_conditions(latched) or "nothing latched"),
            ),
        ),
        step=CURRENT,
    )

    # ── How far one turn is, on this driver as it stands ─────────────────────

    chopconf = fw_api.tmc2209_chopconf_decode(
        raw.read(idx=idx, reg=int(fw_api.TMC2209_CHOPCONF)).value
    )
    microsteps = int(fw_api.tmc2209_mres_microsteps(chopconf.mres))
    plan = _plan(microsteps)

    yield StepOutcome(
        PASSED,
        f"one turn is {plan['pulses']} pulses at {microsteps} microsteps, "
        f"cruising at {plan['cruise_pps']} pps",
        Result(
            level=Level.OK,
            summary=f"{plan['pulses']} pulses in about {TURN_SECONDS:g} s",
            note="Read off CHOPCONF rather than assumed, so a profile at another "
            f"resolution turns the same distance. {FULL_STEPS_PER_TURN} full "
            "steps per revolution is the one thing taken on faith: a 0.9 degree "
            "motor will go round twice.",
            table=Table(
                head=("quantity", "value"),
                rows=(
                    ("microsteps per full step", str(microsteps)),
                    ("pulses", str(plan["pulses"])),
                    ("pull-in", f"{plan['pullin_pps']} pps"),
                    ("cruise", f"{plan['cruise_pps']} pps"),
                    ("acceleration", f"{plan['accel_pps_s']} pps/s"),
                    ("direction", "DIR high" if direction else "DIR low"),
                ),
            ),
        ),
        step=PLAN,
    )

    # ── Does the far end of the wire move ───────────────────────────────────

    samples, high, changes, probed = _step_wire_probe(raw, idx)
    low = samples - high
    minority = min(high, low) / samples if samples else 0.0
    carries = changes > 0 and minority >= PROBE_MINORITY

    yield StepOutcome(
        PASSED if carries else WARNED,
        f"STEP arrives: the driver's own pin changed {changes} times in "
        f"{PROBE_SECONDS:g} s"
        if carries
        else f"STEP never arrives: {samples} samples, all "
        f"{'high' if high else 'low'}, against {probed} pulses emitted",
        Result(
            level=Level.OK if carries else Level.WARN,
            summary="the wire carries" if carries else "the wire does not carry",
            note="Slow on purpose. At the rate the turn below runs, the pin "
            "changes faster than this link can sample it, and every reading "
            "would come back the same whether or not the wire carried. The "
            f"power stage is still off, so the {probed} pulses this cost turned "
            "nothing."
            if carries
            else "The pad toggled, since the counter watching it says so, and "
            "the far end never did. The turn below will emit its pulses and "
            "move nothing, which the readings after it will confirm.",
            table=Table(
                head=("reading", "value"),
                rows=(
                    (
                        "probe rate",
                        f"{PROBE_PPS} pps, {1000 / (2 * PROBE_PPS):.0f} ms per half",
                    ),
                    ("samples", str(samples)),
                    ("read high", str(high)),
                    ("read low", str(low)),
                    ("it changed", f"{changes} times"),
                    ("pulses this cost", str(probed)),
                ),
            ),
        ),
        step=PROBE,
    )

    # ── On, and turning ──────────────────────────────────────────────────────

    raw.enable(idx=idx, on=True)
    on = raw.is_enabled(idx=idx).on
    driven = _driven(raw, idx)
    seen = _seen(raw, idx)

    if not on:
        raise Abandoned("the driver will not report its power stage enabled", FAILED)
    yield StepOutcome(
        PASSED,
        "power stage on, holding position",
        Result(
            level=Level.OK,
            summary="ENN low and the coils are energised",
            table=_pin_rows(driven, seen),
        ),
        step=ENABLE,
    )

    started = time.monotonic()
    try:
        raw.move(idx=idx, dir=direction, shaft=False, **plan)
    except Exception as exc:
        raw.enable(idx=idx, on=False)
        raise Abandoned(f"the move was refused: {exc}", FAILED) from exc

    yield StepOutcome(
        PASSED,
        f"{plan['pulses']} pulses commanded with DIR {'high' if direction else 'low'}",
        Result(
            level=Level.OK,
            summary="the run is in flight and nothing on the board will end it",
            note="A run outlives the call that started it. This routine owns "
            "stopping it, and does so by running out of pulses.",
        ),
        step=MOVE,
    )

    # ── Halfway, while it is still true ──────────────────────────────────────

    time.sleep(TURN_SECONDS / 2)
    midway = raw.motion_report(idx=idx)

    yield StepOutcome(
        PASSED if midway.running else WARNED,
        f"midway: {midway.emitted} of {plan['pulses']} pulses out at "
        f"{midway.rate_pps} pps, {'running' if midway.running else 'already stopped'}",
        Result(
            level=Level.OK if midway.running else Level.WARN,
            summary=f"{midway.emitted} pulses emitted, {midway.rate_pps} pps",
            note="Counted off the pulse counter watching the pin, not off the "
            "encoder, so this is what left the pad. DIR and shaft are the ones "
            "the counted run was started with, which is the only record of them "
            "once the pins move on.",
            table=_report_table(midway, plan["pulses"], time.monotonic() - started),
        ),
        step=MIDWAY,
    )

    # ── What the driver makes of being driven ────────────────────────────────

    # Two samples with every other read between them. The driver advances the
    # table by 256/microsteps for each pulse it receives, so at any rate worth
    # commanding these two cannot come back equal unless nothing is arriving.
    was_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
    tstep = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_TSTEP)).value
    load = raw.poll_load(idx=idx)
    moving = _health(raw, idx)
    live = {int(reg): raw.poll_raw(idx=idx, reg=int(reg)).value for reg in WATCHED}
    now_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value

    advanced = (now_at - was_at) % MSCNT_WRAP
    per_pulse = MSCNT_WRAP // (FULL_STEPS_PER_ELECTRICAL_TURN * microsteps)
    counted, _ = _counter_pps(raw, idx, per_pulse)
    status = fw_api.tmc2209_drv_status_decode(live[int(fw_api.TMC2209_DRV_STATUS)])
    currents = fw_api.tmc2209_mscuract_decode(live[int(fw_api.TMC2209_MSCURACT)])
    pwm = fw_api.tmc2209_pwm_scale_decode(live[int(fw_api.TMC2209_PWM_SCALE)])

    measured = _measured_pps(tstep, microsteps)
    commanded = midway.rate_pps or plan["cruise_pps"]
    off_by = abs(measured - commanded) / commanded if measured and commanded else None
    rate_agrees = off_by is not None and off_by <= FCLK_TOLERANCE

    driven = _driven(raw, idx)
    seen = _seen(raw, idx)
    dir_agrees = bool(seen.dir) == direction

    rows = [
        ("TSTEP", f"{tstep}" + (" (nothing timed)" if measured is None else "")),
        (
            "rate the driver timed",
            f"{measured:.0f} pps" if measured else "no step interval to time",
        ),
        ("rate the firmware reports", f"{commanded} pps"),
        ("they differ by", f"{off_by:.1%}" if off_by is not None else "not comparable"),
        ("microstep position", f"{was_at} then {now_at}"),
        ("it advanced by", f"{advanced}, at {per_pulse} per pulse"),
        (
            "rate the counter timed",
            f"{counted:.0f} pps" if counted else "not moving",
        ),
        ("chopper", "StealthChop" if status.stealth else "SpreadCycle"),
        ("CS_ACTUAL", str(status.cs_actual)),
        ("coil currents", f"A {currents.cur_a}, B {currents.cur_b}"),
        ("PWM_SCALE_SUM", str(pwm.sum)),
        ("StallGuard", f"{load.value}" if load.usable else f"{load.value}, unusable"),
        ("DIR at the driver", "high" if seen.dir else "low"),
    ]

    # Three ways of asking the same question, none of which shares a path with
    # the pulse counter: the driver's own step timer, its standstill flag, and
    # its microstep table. The firmware's count cannot corroborate any of them,
    # because it counts the pad the ESP32 drives and not the pin at the far end.
    unseen = [
        reason
        for reason, holds in (
            ("its step timer timed nothing", measured is None),
            ("it reports standstill", bool(status.stst)),
            ("its microstep counter did not move", advanced == 0),
        )
        if holds
    ]

    concerns = []
    if midway.running and unseen:
        concerns.append(
            "the firmware emitted pulses the driver never saw, because "
            + " and ".join(unseen)
            + ": STEP is not reaching it"
        )
    if not rate_agrees and measured:
        concerns.append("the driver timed a rate the firmware did not command")
    if not dir_agrees:
        concerns.append("DIR does not reach the driver")
    if moving & fw_api.TMC2209_OPEN_LOAD:
        concerns.append("open load with current flowing, so a coil is not connected")

    # A run in flight should have the driver reporting nothing at all, so at rest
    # is the only state where standstill and open load go without saying. And
    # standstill needs no second mention once it has been read as pulses missing.
    if not midway.running:
        accounted = AT_REST
    elif unseen:
        accounted = fw_api.TMC2209_STANDSTILL
    else:
        accounted = fw_api.Tmc2209Condition(0)

    other = moving & ~accounted
    if other:
        concerns.append(named_conditions(other))

    yield StepOutcome(
        WARNED if concerns else PASSED,
        "; ".join(concerns)
        if concerns
        else f"the driver timed {measured:.0f} pps against the {commanded} commanded"
        if measured
        else "the driver reports nothing unusual",
        Result(
            level=Level.WARN if concerns else Level.OK,
            summary="the pulses are not arriving at the driver"
            if midway.running and unseen
            else f"conditions: {named_conditions(moving) or 'nothing reported'}",
            note="The count the firmware reports comes off a counter watching the "
            "ESP32's own pad, so it proves the pulse train exists and says "
            "nothing about the wire. Everything in this table is the driver's "
            "own account, which is the other end of that wire. TSTEP is timed "
            f"against an oscillator trimmed to within {FCLK_TOLERANCE:.0%}, so "
            "that much disagreement on the rate is the clock and not the ramp.",
            fields=(("conditions", hex_word(int(moving))),),
            table=Table(head=("reading", "value"), rows=tuple(rows)),
        ),
        step=DIAGNOSE,
    )

    # ── After the last pulse ─────────────────────────────────────────────────

    time.sleep(max(0.0, TURN_SECONDS - (time.monotonic() - started)) + SETTLE_MARGIN_S)
    final = raw.motion_report(idx=idx)

    if final.running:
        raw.halt(idx=idx, immediate=False)
        time.sleep(SETTLE_MARGIN_S)
        final = raw.motion_report(idx=idx)

    short_by = plan["pulses"] - final.emitted
    yield StepOutcome(
        PASSED if not final.running and short_by == 0 else WARNED,
        f"stopped after {final.emitted} of {plan['pulses']} pulses"
        if not final.running
        else "still running after being halted",
        Result(
            level=Level.OK if not final.running and short_by == 0 else Level.WARN,
            summary="running is false and the count is exact"
            if not final.running and short_by == 0
            else f"running={final.running}, short by {short_by}",
            note="A bounded run emits what it was asked for and not one more, so "
            "any difference here is pulses that left the pad uncounted or never "
            "left it. The count survives the end of the run and stays readable "
            "until the next move replaces it. The average should land on the "
            f"{TURN_SECONDS:g} s the plan was built for.",
            table=_report_table(final, plan["pulses"], time.monotonic() - started),
        ),
        step=SETTLED,
    )

    # ── Back to how it was found ─────────────────────────────────────────────

    resting = _health(raw, idx)
    raw.enable(idx=idx, on=False)
    off = raw.is_enabled(idx=idx).on
    driven = _driven(raw, idx)
    seen = _seen(raw, idx)

    unexpected = resting & ~AT_REST
    yield StepOutcome(
        WARNED if unexpected or off else PASSED,
        f"at rest: {named_conditions(resting) or 'nothing reported'}, power stage off",
        Result(
            level=Level.WARN if unexpected or off else Level.OK,
            summary=named_conditions(unexpected)
            if unexpected
            else "standing still, power stage off",
            note="Standstill and open load are what a stopped driver reports, so "
            "neither is held against it. Their coming back is the other half of "
            "the open load test: present at rest, gone while turning.",
            fields=(("conditions", hex_word(int(resting))),),
            table=_pin_rows(driven, seen),
        ),
        step=REST,
    )


# ── The same turn, driven from inside the driver ─────────────────────────────

DRIVE = "Drive"
STOP = "Stop"


@bench_api.routine(
    hazardous=True,
    steps=[IDENTIFY, BRING_UP, ENABLE, DRIVE, DIAGNOSE, STOP, REST],
    inputs=[
        bench_api.choice("idx", devices, hint=DEVICE),
        bench_api.choice(
            "profile",
            device_profile.names,
            hint="Which profile to bring the driver up on before it turns.",
        ),
        bench_api.integer(
            "velocity",
            unit="VACTUAL",
            min=0,
            max=VELOCITY_MAX,
            hint="1/256 microsteps per 2^24 clocks. Blank is zero, which turns "
            "nothing. Around 10000 is a slow, unmistakable few RPM.",
        ),
        bench_api.boolean("reverse", hint="Drive the velocity negative."),
    ],
)
def velocity_turn(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Turn a shaft from VACTUAL, with the STEP pin doing nothing.

    The control experiment for `one_turn`. Motion comes from the driver's own
    velocity register over the same UART that configured it, so the STEP pin,
    its wire, the RMT channel and the ramp are all out of the circuit. A driver
    that turns here and not there has a pulse path problem and nothing else; one
    that turns in neither has a driver, motor, supply or current problem, and
    the difference is worth far more than either result alone.

    There is no ramp. VACTUAL steps straight from nothing to the rate asked for,
    so the speed at which the shaft stops keeping up is this motor's pull-in
    rate under this load, which is the one number `one_turn` cannot discover and
    must be given.

    Ends with VACTUAL back at zero, which is not tidiness: the library refuses to
    start a pulse-driven move while the velocity register is claiming the motor.
    """
    raw = transport.firmware().raw
    idx = values["idx"]
    profile = values["profile"]
    asked = int(values["velocity"])
    velocity = -asked if values["reverse"] else asked

    version = raw.poll_version(idx=idx).version
    seen = _seen(raw, idx)
    if version != TMC2209_VERSION:
        raise Abandoned(
            f"the part answered version 0x{version:02x}, not a TMC2209", FAILED
        )
    yield StepOutcome(
        PASSED,
        f"a TMC2209 answers here, strapped to address {_strapped(seen)}",
        Result(
            level=Level.OK,
            summary=f"version 0x{version:02x}, address {_strapped(seen)}",
            fields=flag_rows(seen),
        ),
        step=IDENTIFY,
    )

    try:
        ops = device_profile.ops(device_profile.load(profile))
    except Exception as exc:
        raise Abandoned(
            f"{profile} cannot be given to this driver: {exc}", FAILED
        ) from exc

    raw.enable(idx=idx, on=False)
    found = raw.bringup(idx=idx, ops=list(ops))
    agreed = raw.verify_config(idx=idx)
    if not agreed.agrees:
        raise Abandoned(
            "the driver disagrees with what was written: "
            + (
                ", ".join(device_profile.slot_names(agreed.mismatched))
                or "no register named"
            ),
            FAILED,
        )
    raw.set_current(
        idx=idx, ihold=SPIN_IHOLD, irun=SPIN_IRUN, iholddelay=SPIN_IHOLDDELAY
    )
    yield StepOutcome(
        PASSED,
        f"{profile} is on the driver, GSTAT was {hex_word(found.gstat_at_bringup)}",
        Result(
            level=Level.OK,
            summary=f"{len(ops)} owned registers written, IRUN {SPIN_IRUN}",
            note="VACTUAL is one of the owned registers and the profile writes it "
            "as zero, so the driver is standing still by configuration before "
            "anything below asks it to move.",
            fields=flag_rows(fw_api.tmc2209_gstat_decode(found.gstat_at_bringup)),
        ),
        step=BRING_UP,
    )

    microsteps = int(
        fw_api.tmc2209_mres_microsteps(
            fw_api.tmc2209_chopconf_decode(
                raw.read(idx=idx, reg=int(fw_api.TMC2209_CHOPCONF)).value
            ).mres
        )
    )
    wanted = _velocity_pps(velocity)

    raw.enable(idx=idx, on=True)
    if not raw.is_enabled(idx=idx).on:
        raise Abandoned("the driver will not report its power stage enabled", FAILED)
    yield StepOutcome(
        PASSED,
        "power stage on, holding position",
        Result(
            level=Level.OK,
            summary="ENN low and the coils are energised",
            table=_pin_rows(_driven(raw, idx), _seen(raw, idx)),
        ),
        step=ENABLE,
    )

    started = time.monotonic()
    try:
        raw.set_velocity(idx=idx, velocity=velocity)
    except Exception as exc:
        raw.enable(idx=idx, on=False)
        raise Abandoned(f"the velocity was refused: {exc}", FAILED) from exc

    yield StepOutcome(
        PASSED,
        f"VACTUAL {velocity}, asking for {wanted:.0f} pps "
        f"({_rpm(wanted, microsteps):.1f} RPM)",
        Result(
            level=Level.OK,
            summary="the driver is stepping itself, with STEP idle",
            note="Nothing counts these. The pulse counter is watching a pin that "
            "is not moving, so the only record of what happened is the driver's "
            "own microstep counter, read below.",
            table=Table(
                head=("quantity", "value"),
                rows=(
                    ("VACTUAL", str(velocity)),
                    ("microsteps per full step", str(microsteps)),
                    ("asks for", f"{wanted:.0f} pps"),
                    ("which is", f"{_rpm(wanted, microsteps):.1f} RPM"),
                ),
            ),
        ),
        step=DRIVE,
    )

    time.sleep(VELOCITY_SECONDS / 2)
    was_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
    tstep = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_TSTEP)).value
    load = raw.poll_load(idx=idx)
    moving = _health(raw, idx)
    status = fw_api.tmc2209_drv_status_decode(
        raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_DRV_STATUS)).value
    )
    currents = fw_api.tmc2209_mscuract_decode(
        raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCURACT)).value
    )
    now_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value

    advanced = (now_at - was_at) % MSCNT_WRAP
    per_pulse = MSCNT_WRAP // (FULL_STEPS_PER_ELECTRICAL_TURN * microsteps)
    counted, _ = _counter_pps(raw, idx, per_pulse)
    measured = _measured_pps(tstep, microsteps)
    off_by = abs(measured - wanted) / wanted if measured and wanted else None

    concerns = []
    if velocity and status.stst:
        concerns.append("the driver reports standstill while VACTUAL is set")
    if velocity and advanced == 0:
        concerns.append("the microstep counter did not move")
    if off_by is not None and off_by > FCLK_TOLERANCE:
        # Both ends of this come from inside the driver, so unlike one_turn there
        # is no wire between them and the clock cannot explain a large gap.
        concerns.append("the driver is not stepping itself at the rate it was set")
    if moving & fw_api.TMC2209_OPEN_LOAD:
        concerns.append("open load with current flowing, so a coil is not connected")
    # Turning, so nothing should be reported at all. The two that a stopped
    # driver reports are excluded here only because each already has its own
    # line above, not because either is unremarkable while it is moving.
    other = moving & ~AT_REST
    if velocity and other:
        concerns.append(named_conditions(other))

    yield StepOutcome(
        WARNED if concerns else PASSED,
        "; ".join(concerns)
        if concerns
        else f"the driver timed {measured:.0f} pps against the {wanted:.0f} asked for"
        if measured
        else "the driver reports nothing unusual",
        Result(
            level=Level.WARN if concerns else Level.OK,
            summary=f"conditions: {named_conditions(moving) or 'nothing reported'}",
            note="If the shaft is turning here but not under one_turn, everything "
            "except the pulse path is proven: this route reaches the motor over "
            "the UART and never touches the STEP pin.",
            fields=(("conditions", hex_word(int(moving))),),
            table=Table(
                head=("reading", "value"),
                rows=(
                    (
                        "TSTEP",
                        f"{tstep}" + (" (nothing timed)" if measured is None else ""),
                    ),
                    (
                        "rate the driver timed",
                        f"{measured:.0f} pps"
                        if measured
                        else "no step interval to time",
                    ),
                    ("rate VACTUAL asks for", f"{wanted:.0f} pps"),
                    (
                        "they differ by",
                        f"{off_by:.1%}" if off_by is not None else "not comparable",
                    ),
                    (
                        "rate the counter timed",
                        f"{counted:.0f} pps" if counted else "not moving",
                    ),
                    ("which is", f"{_rpm(wanted, microsteps):.1f} RPM asked for"),
                    ("microstep position", f"{was_at} then {now_at}"),
                    ("it advanced by", f"{advanced}, at {per_pulse} per pulse"),
                    ("chopper", "StealthChop" if status.stealth else "SpreadCycle"),
                    ("CS_ACTUAL", str(status.cs_actual)),
                    ("coil currents", f"A {currents.cur_a}, B {currents.cur_b}"),
                    (
                        "StallGuard",
                        f"{load.value}" if load.usable else f"{load.value}, unusable",
                    ),
                ),
            ),
        ),
        step=DIAGNOSE,
    )

    time.sleep(max(0.0, VELOCITY_SECONDS - (time.monotonic() - started)))
    raw.set_velocity(idx=idx, velocity=0)
    held = raw.read(idx=idx, reg=int(fw_api.TMC2209_VACTUAL)).value
    yield StepOutcome(
        PASSED if held == 0 else WARNED,
        "VACTUAL back to zero, so the STEP pin owns motion again"
        if held == 0
        else f"VACTUAL still reads {held}",
        Result(
            level=Level.OK if held == 0 else Level.WARN,
            summary=f"ran for {time.monotonic() - started:.2f} s",
            note="A move refuses to start while VACTUAL claims the motor, so "
            "leaving this set would have one_turn fail with an access refusal "
            "rather than anything that names the cause.",
            fields=(("VACTUAL", str(held)),),
        ),
        step=STOP,
    )

    resting = _health(raw, idx)
    raw.enable(idx=idx, on=False)
    yield StepOutcome(
        PASSED,
        f"at rest: {named_conditions(resting) or 'nothing reported'}, power stage off",
        Result(
            level=Level.OK,
            summary="standing still, power stage off",
            fields=(("conditions", hex_word(int(resting))),),
            table=_pin_rows(_driven(raw, idx), _seen(raw, idx)),
        ),
        step=REST,
    )
