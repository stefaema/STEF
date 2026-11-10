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
from typing import TYPE_CHECKING, Any

from shared import fw_api
from shared.diagnostics import Failed, Test, end, step
from shared.subsystem import Level, Result, Table, boolean, choice, integer
from transport import device_profile
from transport.bench import spin_measure
from transport.bench.calls import DEVICE, devices
from transport.bench.setup import flag_rows, hex_word, named_conditions
from transport.bench.spin_measure import (
    AT_REST,
    FCLK_TOLERANCE,
    FULL_STEPS_PER_ELECTRICAL_TURN,
    FULL_STEPS_PER_TURN,
    LATCHED,
    MSCNT_WRAP,
    PROBE_MINORITY,
    PROBE_PPS,
    PROBE_SECONDS,
    SETTLE_MARGIN_S,
    SPIN_IHOLD,
    SPIN_IHOLDDELAY,
    SPIN_IRUN,
    TMC2209_VERSION,
    TURN_SECONDS,
    VELOCITY_MAX,
    VELOCITY_SECONDS,
    WATCHED,
)

if TYPE_CHECKING:
    from transport.subsystem import Transport

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
DRIVE = "Drive"
STOP = "Stop"

PROFILE = choice(
    "profile",
    lambda sub: device_profile.names(),
    hint="Which profile to bring the driver up on before it turns.",
)


class Spin(Test[Any]):
    sub: Transport

    @step(IDENTIFY)
    def identify(self) -> None:
        self.raw = raw = self.sub.firmware().raw
        self.idx = idx = self.values["idx"]

        version = raw.poll_version(idx=idx).version
        seen = spin_measure.seen(raw, idx)
        strapped = spin_measure.strapped(seen)
        declared = spin_measure.declared_address(self.sub, idx)

        if version != TMC2209_VERSION:
            raise Failed(
                f"the part answered version 0x{version:02x}, and a TMC2209 answers "
                f"0x{TMC2209_VERSION:02x}",
                Result(
                    level=Level.ERROR,
                    summary=f"version 0x{version:02x} is not a TMC2209",
                    note="Either something else is on this address or the reply was "
                    "corrupted on the way back.",
                ),
            )

        mismatched_address = declared is not None and declared != strapped
        said = self.warn if mismatched_address else self.report
        said(
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
        )

    @end(REST)
    def at_rest(self) -> None:
        raw = self.sub.firmware().raw
        idx = self.values["idx"]

        if raw.motion_report(idx=idx).pulsing:
            raw.halt(idx=idx, immediate=False)
            time.sleep(SETTLE_MARGIN_S)
        raw.set_velocity(idx=idx, velocity=0)
        resting = spin_measure.health(raw, idx)
        raw.enable(idx=idx, on=False)
        off = raw.is_enabled(idx=idx).on
        driven = spin_measure.driven(raw, idx)
        seen = spin_measure.seen(raw, idx)

        unexpected = resting & ~AT_REST
        said = self.warn if unexpected or off else self.report
        said(
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
                table=spin_measure.pin_rows(driven, seen),
            ),
        )
        if off:
            raise RuntimeError(
                "the driver still reports its power stage enabled after being told off"
            )


class OneTurn(Spin):
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

    inputs = (
        choice("idx", devices, hint=DEVICE),
        PROFILE,
        boolean(
            "dir",
            hint="The level to drive on DIR. Electrical, so which way it turns "
            "depends on how the coils are wired.",
        ),
    )
    turned = boolean("turned", hint="Did the shaft turn one full revolution?")

    # ── Off before anything else happens ─────────────────────────────────────

    @step(DISABLE)
    def disable(self) -> None:
        raw, idx = self.raw, self.idx
        self.direction = bool(self.values["dir"])
        raw.enable(idx=idx, on=False)
        off = raw.is_enabled(idx=idx).on
        driven = spin_measure.driven(raw, idx)
        seen = spin_measure.seen(raw, idx)
        disagreeing = spin_measure.disagreeing(driven, seen)

        if off:
            raise Failed(
                "the driver still reports its power stage enabled after being told off"
            )
        differing = ", ".join(disagreeing)
        said = self.warn if disagreeing else self.report
        said(
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
                table=spin_measure.pin_rows(driven, seen),
            ),
        )

    # ── The configuration it will turn on ────────────────────────────────────

    @step(BRING_UP, hazard="rewrites every owned register")
    def bring_up(self) -> None:
        raw, idx = self.raw, self.idx
        profile = self.values["profile"]
        try:
            ops = device_profile.ops(device_profile.load(profile))
        except Exception as exc:
            raise Failed(
                f"{profile} is not a configuration this driver can be given: {exc}"
            ) from exc

        found = raw.bringup(idx=idx, ops=list(ops))
        agreed = raw.verify_config(idx=idx)
        valid = raw.all_owned_valid(idx=idx).valid

        if not agreed.agrees:
            differing = ", ".join(device_profile.slot_names(agreed.mismatched))
            raise Failed(
                f"the driver disagrees with what was written: {differing or 'no register named'}",
                Result(
                    level=Level.ERROR,
                    summary="the driver holds something else",
                    fields=(("mismatched", hex_word(agreed.mismatched)),),
                ),
            )
        said = self.report if valid else self.warn
        said(
            f"{profile} is on the driver, GSTAT was "
            f"{hex_word(found.gstat_found)} when it was claimed",
            Result(
                level=Level.OK if valid else Level.WARN,
                summary=f"{len(ops)} owned registers written and agreed",
                note="GSTAT as found is the only look anyone gets at what the driver "
                "went through before this firmware owned it.",
                fields=(("all_owned_valid", "true" if valid else "false"),)
                + flag_rows(fw_api.tmc2209_gstat_decode(found.gstat_found)),
            ),
        )

        self.standing = spin_measure.health(raw, idx)
        self.latched = self.standing & LATCHED
        if self.latched:
            raw.clear_faults(idx=idx, conditions=int(self.latched))
            self.standing = spin_measure.health(raw, idx)

    # ── A current a printed flag can be turned with ──────────────────────────

    @step(CURRENT, hazard="changes the coil current")
    def current(self) -> None:
        self.raw.set_current(
            idx=self.idx, ihold=SPIN_IHOLD, irun=SPIN_IRUN, iholddelay=SPIN_IHOLDDELAY
        )
        self.report(
            f"run current set to CS {SPIN_IRUN}, hold to CS {SPIN_IHOLD}",
            Result(
                level=Level.OK,
                summary=f"IRUN {SPIN_IRUN}, IHOLD {SPIN_IHOLD}, IHOLDDELAY "
                f"{SPIN_IHOLDDELAY}",
                note="About 0.50 A RMS running on 0.11 ohm sense resistors with "
                "vsense off. IHOLD_IRUN is write-only on the part, so this is what "
                "was sent rather than what was read back.",
                fields=(
                    (
                        "conditions after bring-up",
                        named_conditions(self.standing) or "none",
                    ),
                    ("cleared", named_conditions(self.latched) or "nothing latched"),
                ),
            ),
        )

    # ── How far one turn is, on this driver as it stands ─────────────────────

    @step(PLAN)
    def plan(self) -> None:
        chopconf = fw_api.tmc2209_chopconf_decode(
            self.raw.read(idx=self.idx, reg=int(fw_api.TMC2209_CHOPCONF)).value
        )
        self.microsteps = microsteps = int(
            fw_api.tmc2209_mres_microsteps(chopconf.mres)
        )
        self.planned = plan = spin_measure.plan(microsteps)

        self.report(
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
                        ("direction", "DIR high" if self.direction else "DIR low"),
                    ),
                ),
            ),
        )

    # ── Does the far end of the wire move ───────────────────────────────────

    @step(PROBE)
    def probe(self) -> None:
        samples, high, changes, probed = spin_measure.step_wire_probe(
            self.raw, self.idx
        )
        low = samples - high
        minority = min(high, low) / samples if samples else 0.0
        carries = changes > 0 and minority >= PROBE_MINORITY

        said = self.report if carries else self.warn
        said(
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
        )

    # ── On, and turning ──────────────────────────────────────────────────────

    @step(ENABLE, hazard="energises the coils")
    def enable(self) -> None:
        raw, idx = self.raw, self.idx
        raw.enable(idx=idx, on=True)
        on = raw.is_enabled(idx=idx).on
        driven = spin_measure.driven(raw, idx)
        seen = spin_measure.seen(raw, idx)

        if not on:
            raise Failed("the driver will not report its power stage enabled")
        self.report(
            "power stage on, holding position",
            Result(
                level=Level.OK,
                summary="ENN low and the coils are energised",
                table=spin_measure.pin_rows(driven, seen),
            ),
        )

    @step(MOVE, hazard="turns the shaft")
    def move(self) -> None:
        plan = self.planned
        self.started = time.monotonic()
        try:
            self.raw.move(idx=self.idx, dir=self.direction, shaft=False, **plan)
        except Exception as exc:
            raise Failed(f"the move was refused: {exc}") from exc

        self.report(
            f"{plan['pulses']} pulses commanded with DIR {'high' if self.direction else 'low'}",
            Result(
                level=Level.OK,
                summary="the run is in flight and nothing on the board will end it",
                note="A run outlives the call that started it. This routine owns "
                "stopping it, and does so by running out of pulses.",
            ),
        )

    # ── Halfway, while it is still true ──────────────────────────────────────

    @step(MIDWAY)
    def midway(self) -> None:
        plan = self.planned
        time.sleep(TURN_SECONDS / 2)
        self.halfway = midway = self.raw.motion_report(idx=self.idx)

        said = self.report if midway.pulsing else self.warn
        said(
            f"midway: {midway.emitted} of {plan['pulses']} pulses out at "
            f"{midway.rate_pps} pps, {'running' if midway.pulsing else 'already stopped'}",
            Result(
                level=Level.OK if midway.pulsing else Level.WARN,
                summary=f"{midway.emitted} pulses emitted, {midway.rate_pps} pps",
                note="Counted off the pulse counter watching the pin, not off the "
                "encoder, so this is what left the pad. DIR and shaft are the ones "
                "the counted run was started with, which is the only record of them "
                "once the pins move on.",
                table=spin_measure.report_table(
                    midway, plan["pulses"], time.monotonic() - self.started
                ),
            ),
        )

    # ── What the driver makes of being driven ────────────────────────────────

    @step(DIAGNOSE)
    def diagnose(self) -> None:
        raw, idx, plan, midway = self.raw, self.idx, self.planned, self.halfway
        microsteps = self.microsteps

        # Two samples with every other read between them. The driver advances the
        # table by 256/microsteps for each pulse it receives, so at any rate worth
        # commanding these two cannot come back equal unless nothing is arriving.
        was_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
        tstep = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_TSTEP)).value
        load = raw.poll_load(idx=idx)
        moving = spin_measure.health(raw, idx)
        live = {int(reg): raw.poll_raw(idx=idx, reg=int(reg)).value for reg in WATCHED}
        now_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value

        advanced = (now_at - was_at) % MSCNT_WRAP
        per_pulse = MSCNT_WRAP // (FULL_STEPS_PER_ELECTRICAL_TURN * microsteps)
        counted, _ = spin_measure.counter_pps(raw, idx, per_pulse)
        status = fw_api.tmc2209_drv_status_decode(live[int(fw_api.TMC2209_DRV_STATUS)])
        currents = fw_api.tmc2209_mscuract_decode(live[int(fw_api.TMC2209_MSCURACT)])
        pwm = fw_api.tmc2209_pwm_scale_decode(live[int(fw_api.TMC2209_PWM_SCALE)])

        measured = spin_measure.measured_pps(tstep, microsteps)
        commanded = midway.rate_pps or plan["cruise_pps"]
        off_by = (
            abs(measured - commanded) / commanded if measured and commanded else None
        )
        rate_agrees = off_by is not None and off_by <= FCLK_TOLERANCE

        seen = spin_measure.seen(raw, idx)
        dir_agrees = bool(seen.dir) == self.direction

        self.measure("rate the driver timed", measured, unit="pps")
        self.measure("rate the firmware reports", commanded, unit="pps")
        self.measure("rate the counter timed", counted, unit="pps")

        rows = [
            ("TSTEP", f"{tstep}" + (" (nothing timed)" if measured is None else "")),
            (
                "rate the driver timed",
                f"{measured:.0f} pps" if measured else "no step interval to time",
            ),
            ("rate the firmware reports", f"{commanded} pps"),
            (
                "they differ by",
                f"{off_by:.1%}" if off_by is not None else "not comparable",
            ),
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
            (
                "StallGuard",
                f"{load.value}" if load.usable else f"{load.value}, unusable",
            ),
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
        if midway.pulsing and unseen:
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
            concerns.append(
                "open load with current flowing, so a coil is not connected"
            )

        # A run in flight should have the driver reporting nothing at all, so at rest
        # is the only state where standstill and open load go without saying. And
        # standstill needs no second mention once it has been read as pulses missing.
        if not midway.pulsing:
            accounted = AT_REST
        elif unseen:
            accounted = fw_api.TMC2209_STANDSTILL
        else:
            accounted = fw_api.Tmc2209Condition(0)

        other = moving & ~accounted
        if other:
            concerns.append(named_conditions(other))

        said = self.warn if concerns else self.report
        said(
            "; ".join(concerns)
            if concerns
            else f"the driver timed {measured:.0f} pps against the {commanded} commanded"
            if measured
            else "the driver reports nothing unusual",
            Result(
                level=Level.WARN if concerns else Level.OK,
                summary="the pulses are not arriving at the driver"
                if midway.pulsing and unseen
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
        )

    # ── After the last pulse ─────────────────────────────────────────────────

    @step(SETTLED)
    def settled(self) -> None:
        raw, idx, plan = self.raw, self.idx, self.planned
        time.sleep(
            max(0.0, TURN_SECONDS - (time.monotonic() - self.started)) + SETTLE_MARGIN_S
        )
        final = raw.motion_report(idx=idx)

        if final.pulsing:
            raw.halt(idx=idx, immediate=False)
            time.sleep(SETTLE_MARGIN_S)
            final = raw.motion_report(idx=idx)

        short_by = plan["pulses"] - final.emitted
        exact = not final.pulsing and short_by == 0
        shown = Result(
            level=Level.OK if exact else Level.WARN,
            summary="pulsing is false and the count is exact"
            if exact
            else f"pulsing={final.pulsing}, short by {short_by}",
            note="A bounded run emits what it was asked for and not one more, so "
            "any difference here is pulses that left the pad uncounted or never "
            "left it. The count survives the end of the run and stays readable "
            "until the next move replaces it. The average should land on the "
            f"{TURN_SECONDS:g} s the plan was built for.",
            table=spin_measure.report_table(
                final, plan["pulses"], time.monotonic() - self.started
            ),
        )
        if not self.ask(self.turned):
            raise Failed(
                f"the firmware emitted {final.emitted} pulses and the operator saw "
                "no full turn",
                shown,
            )
        said = self.report if exact else self.warn
        said(
            f"stopped after {final.emitted} of {plan['pulses']} pulses"
            if not final.pulsing
            else "still running after being halted",
            shown,
        )


# ── The same turn, driven from inside the driver ─────────────────────────────


class VelocityTurn(Spin):
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

    inputs = (
        choice("idx", devices, hint=DEVICE),
        PROFILE,
        integer(
            "velocity",
            unit="VACTUAL",
            min=0,
            max=VELOCITY_MAX,
            hint="1/256 microsteps per 2^24 clocks. Blank is zero, which turns "
            "nothing. Around 10000 is a slow, unmistakable few RPM.",
        ),
        boolean("reverse", hint="Drive the velocity negative."),
    )
    turning = boolean("turning", hint="Is the shaft turning?")

    @step(BRING_UP, hazard="rewrites every owned register")
    def bring_up(self) -> None:
        raw, idx = self.raw, self.idx
        profile = self.values["profile"]
        asked = int(self.values["velocity"])
        self.velocity = -asked if self.values["reverse"] else asked
        try:
            ops = device_profile.ops(device_profile.load(profile))
        except Exception as exc:
            raise Failed(f"{profile} cannot be given to this driver: {exc}") from exc

        raw.enable(idx=idx, on=False)
        found = raw.bringup(idx=idx, ops=list(ops))
        agreed = raw.verify_config(idx=idx)
        if not agreed.agrees:
            raise Failed(
                "the driver disagrees with what was written: "
                + (
                    ", ".join(device_profile.slot_names(agreed.mismatched))
                    or "no register named"
                )
            )
        raw.set_current(
            idx=idx, ihold=SPIN_IHOLD, irun=SPIN_IRUN, iholddelay=SPIN_IHOLDDELAY
        )
        self.report(
            f"{profile} is on the driver, GSTAT was {hex_word(found.gstat_found)}",
            Result(
                level=Level.OK,
                summary=f"{len(ops)} owned registers written, IRUN {SPIN_IRUN}",
                note="VACTUAL is one of the owned registers and the profile writes it "
                "as zero, so the driver is standing still by configuration before "
                "anything below asks it to move.",
                fields=flag_rows(fw_api.tmc2209_gstat_decode(found.gstat_found)),
            ),
        )

        self.microsteps = int(
            fw_api.tmc2209_mres_microsteps(
                fw_api.tmc2209_chopconf_decode(
                    raw.read(idx=idx, reg=int(fw_api.TMC2209_CHOPCONF)).value
                ).mres
            )
        )
        self.wanted = spin_measure.velocity_pps(self.velocity)

    @step(ENABLE, hazard="energises the coils")
    def enable(self) -> None:
        raw, idx = self.raw, self.idx
        raw.enable(idx=idx, on=True)
        if not raw.is_enabled(idx=idx).on:
            raise Failed("the driver will not report its power stage enabled")
        self.report(
            "power stage on, holding position",
            Result(
                level=Level.OK,
                summary="ENN low and the coils are energised",
                table=spin_measure.pin_rows(
                    spin_measure.driven(raw, idx), spin_measure.seen(raw, idx)
                ),
            ),
        )

    @step(DRIVE, hazard="turns the shaft from VACTUAL")
    def drive(self) -> None:
        velocity, wanted, microsteps = self.velocity, self.wanted, self.microsteps
        self.started = time.monotonic()
        try:
            self.raw.set_velocity(idx=self.idx, velocity=velocity)
        except Exception as exc:
            raise Failed(f"the velocity was refused: {exc}") from exc

        self.report(
            f"VACTUAL {velocity}, asking for {wanted:.0f} pps "
            f"({spin_measure.rpm(wanted, microsteps):.1f} RPM)",
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
                        ("which is", f"{spin_measure.rpm(wanted, microsteps):.1f} RPM"),
                    ),
                ),
            ),
        )

    @step(DIAGNOSE)
    def diagnose(self) -> None:
        raw, idx = self.raw, self.idx
        velocity, wanted, microsteps = self.velocity, self.wanted, self.microsteps

        time.sleep(VELOCITY_SECONDS / 2)
        was_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value
        tstep = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_TSTEP)).value
        load = raw.poll_load(idx=idx)
        moving = spin_measure.health(raw, idx)
        status = fw_api.tmc2209_drv_status_decode(
            raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_DRV_STATUS)).value
        )
        currents = fw_api.tmc2209_mscuract_decode(
            raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCURACT)).value
        )
        now_at = raw.poll_raw(idx=idx, reg=int(fw_api.TMC2209_MSCNT)).value

        advanced = (now_at - was_at) % MSCNT_WRAP
        per_pulse = MSCNT_WRAP // (FULL_STEPS_PER_ELECTRICAL_TURN * microsteps)
        counted, _ = spin_measure.counter_pps(raw, idx, per_pulse)
        measured = spin_measure.measured_pps(tstep, microsteps)
        off_by = abs(measured - wanted) / wanted if measured and wanted else None

        self.measure("rate the driver timed", measured, unit="pps")
        self.measure("rate VACTUAL asks for", wanted, unit="pps")
        self.measure("rate the counter timed", counted, unit="pps")

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
            concerns.append(
                "open load with current flowing, so a coil is not connected"
            )
        # Turning, so nothing should be reported at all. The two that a stopped
        # driver reports are excluded here only because each already has its own
        # line above, not because either is unremarkable while it is moving.
        other = moving & ~AT_REST
        if velocity and other:
            concerns.append(named_conditions(other))

        shown = Result(
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
                    (
                        "which is",
                        f"{spin_measure.rpm(wanted, microsteps):.1f} RPM asked for",
                    ),
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
        )
        if velocity and not self.ask(self.turning):
            raise Failed("VACTUAL is set and the operator saw the shaft still", shown)
        said = self.warn if concerns else self.report
        said(
            "; ".join(concerns)
            if concerns
            else f"the driver timed {measured:.0f} pps against the {wanted:.0f} asked for"
            if measured
            else "the driver reports nothing unusual",
            shown,
        )

    @step(STOP)
    def stop(self) -> None:
        raw, idx = self.raw, self.idx
        time.sleep(max(0.0, VELOCITY_SECONDS - (time.monotonic() - self.started)))
        raw.set_velocity(idx=idx, velocity=0)
        held = raw.read(idx=idx, reg=int(fw_api.TMC2209_VACTUAL)).value
        said = self.report if held == 0 else self.warn
        said(
            "VACTUAL back to zero, so the STEP pin owns motion again"
            if held == 0
            else f"VACTUAL still reads {held}",
            Result(
                level=Level.OK if held == 0 else Level.WARN,
                summary=f"ran for {time.monotonic() - self.started:.2f} s",
                note="A move refuses to start while VACTUAL claims the motor, so "
                "leaving this set would have one_turn fail with an access refusal "
                "rather than anything that names the cause.",
                fields=(("VACTUAL", str(held)),),
            ),
        )
