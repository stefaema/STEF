from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from shared import fw_api
from shared.subsystem import Table

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


def line_name(line: int) -> str:
    """Return one line's name as the datasheet prints it."""
    return fw_api.Tmc2209Line(line).name.removeprefix("TMC2209_LINE_")


def driven(raw: Any, idx: int) -> dict[str, bool | None]:
    """Return what the ESP32 has on each of this driver's pins.

    A line the board does not wire is refused rather than guessed, and a board
    that wires three of the four is a board this should still report on. So a
    refusal is None here and a row that says so later, never an ended run.
    """
    found: dict[str, bool | None] = {}
    for line in LINES:
        try:
            found[line_name(line).lower()] = bool(
                raw.line_read(idx=idx, line=int(line)).level
            )
        except Exception:  # noqa: BLE001
            found[line_name(line).lower()] = None
    return found


def seen(raw: Any, idx: int) -> Any:
    """Return what the driver reports on its own pins, decoded."""
    return fw_api.tmc2209_ioin_decode(raw.poll_pins(idx=idx).value)


def pin_rows(driven: Mapping[str, bool | None], seen: Any) -> Table:
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


def disagreeing(driven: Mapping[str, bool | None], seen: Any) -> tuple[str, ...]:
    """Return the lines whose two ends do not hold the same level."""
    return tuple(
        name.upper()
        for name, ours in driven.items()
        if ours is not None and bool(ours) != bool(getattr(seen, name))
    )


def strapped(seen: Any) -> int:
    """Return the address the MS1 and MS2 straps select, MS1 being the low bit."""
    return (1 if seen.ms1 else 0) | (2 if seen.ms2 else 0)


def declared_address(sub: Any, idx: int) -> int | None:
    """Return the address the board table gives this driver, or None if it cannot say."""
    try:
        return int(sub.firmware().sys.devices().devs[idx].addr)
    except Exception:  # noqa: BLE001
        return None


def measured_pps(tstep: int, microsteps: int) -> float | None:
    """Return the rate the driver timed between microsteps, in pulses per second.

    TSTEP counts in 1/fCLK the interval between two 1/256 microsteps, not between
    two STEP pulses. One pulse advances the internal table by 256/microsteps of
    those, so the pulse rate is that many times slower than TSTEP alone implies.
    A driver that is standing still, or too slow to time, reads all ones.
    """
    if tstep <= 0 or tstep >= 0xFFFFF:
        return None
    return FCLK_HZ * microsteps / (256 * tstep)


def plan(microsteps: int) -> dict[str, int]:
    """Return the run that turns the shaft once in about TURN_SECONDS."""
    pulses = FULL_STEPS_PER_TURN * microsteps
    cruise = round(pulses / (TURN_SECONDS - RAMP_OVERHEAD_S))
    return {
        "pulses": pulses,
        "cruise_pps": cruise,
        "pullin_pps": max(1, cruise // PULLIN_SHARE),
        "accel_pps_s": cruise * RAMP_STEEPNESS,
    }


def velocity_pps(vactual: int) -> float:
    """Return what a VACTUAL setting asks for, as the STEP pulses per second it stands in for.

    VACTUAL counts microsteps at the resolution CHOPCONF is holding, one per
    2^24 / fCLK, so it is already in the units a pulse would have been and takes
    no factor for the microstep count. TSTEP is the one that is normalised to
    1/256 of a fullstep and needs converting, which is the opposite of what the
    two register descriptions read like at a glance.
    """
    return abs(vactual) * FCLK_HZ / VACTUAL_PERIOD


def counter_pps(raw: Any, idx: int, per_pulse: int) -> tuple[float | None, int]:
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


def rpm(pps: float, microsteps: int) -> float:
    """Return a pulse rate as shaft revolutions per minute."""
    return pps * 60 / (microsteps * FULL_STEPS_PER_TURN)


def step_wire_probe(raw: Any, idx: int) -> tuple[int, int, int, int]:
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
        levels.append(bool(seen(raw, idx).step))

    raw.halt(idx=idx, immediate=True)
    emitted = raw.motion_report(idx=idx).emitted

    high = sum(1 for level in levels if level)
    changes = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
    return len(levels), high, changes, emitted


def report_table(report: Any, commanded: int, elapsed: float) -> Table:
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


def health(raw: Any, idx: int) -> fw_api.Tmc2209Condition:
    """Return what the driver reports about itself, as the flag set it stands for."""
    return fw_api.Tmc2209Condition(raw.poll_health(idx=idx).conditions)
