/*
 * tmc2209_stepgen.h: STEP as a rate, not a level.
 *
 * The other two backends are synchronous and stateless. You call tx, bytes
 * move or they do not, and nothing is remembered between calls. That is what
 * lets tmc2209_uart.h and tmc2209_lines.h each say "note what is absent: there
 * is no clock".
 *
 * A pulse train cannot be that. Four thousand microsteps take a fifth of a
 * second, so a call that returned when the motion ended would hold the control
 * task for that whole time, and a call that returns immediately leaves a run
 * in flight, which is state. Spacing edges in time is a clock by definition.
 *
 * So this is the backend that owns time, and it is the only one. What it does
 * not own is meaning. It emits edges on a pin and counts them; it has never
 * heard of DIR, of GCONF.shaft, or of microstep resolution. That is why the
 * count here is in pulses and becomes microsteps one layer up, where
 * CHOPCONF.mres is cached, and millimetres one layer above that.
 *
 * Rates are pulses per second, abbreviated pps. Deliberately not "steps per
 * second": a step is a full step and there are up to 256 pulses inside one.
 */

#ifndef TMC2209_STEPGEN_H
#define TMC2209_STEPGEN_H

#include <stdbool.h>
#include <stdint.h>

/** Shortest STEP high or low time the part will register, from the datasheet.
    A backend must guarantee at least this, which is what min_pulse_ns declares. */
#define TMC2209_STEP_MIN_PULSE_NS 100u

/**
 * @brief What a run is asked to do.
 *
 * Three rates rather than one, because a stepper that is commanded faster than
 * it can physically accelerate falls behind, slips, and moves an unknown
 * distance. There is no encoder anywhere in this machine, so a slip is not
 * detected, it is simply believed. The profile is what prevents it:
 *
 *     rate
 *      ▲
 *      │        ┌─────────────────┐        cruise_pps
 *      │       ╱                   ╲       ← accel_pps_s is these slopes
 *      │  ────┘                     └───   pullin_pps
 *      └────────────────────────────────►  pulses emitted
 *
 * The last pulse matters as much as the first: stopping dead from cruise loses
 * sync exactly as starting at cruise does, and it is the half people forget.
 */
typedef struct {
    uint32_t pulses;       /**< STEP edges to emit. 0 runs until halted */
    uint32_t pullin_pps;   /**< rate of the first and last pulse: the fastest this
                                motor and load can start from rest, and stop dead
                                from, while staying in sync. A property of the
                                mechanism, so it comes from the board table */
    uint32_t cruise_pps;   /**< rate held between the ramps. A run too short to
                                finish accelerating never reaches it, and the
                                profile becomes a triangle */
    uint32_t accel_pps_s;  /**< slope of both ramps. 0 means no ramp at all, which
                                is only coherent when cruise_pps == pullin_pps */
} tmc2209_run_t;

/** @brief A snapshot of a run. Safe to take while one is in flight. */
typedef struct {
    uint32_t emitted;   /**< pulses since this run began. See the note below */
    uint32_t rate_pps;  /**< the rate presently being emitted */
    bool     running;   /**< false once the last pulse is out, or once halted */
} tmc2209_run_state_t;

/**
 * @brief A source of pulses on one driver's STEP pin. One per driver.
 *
 * Every call reports failure as a plain int, as the port and the lines do: a
 * backend knows only that a peripheral accepted the work or did not.
 *
 * What an implementation must guarantee:
 *
 *   - **Exact counts.** A bounded run emits @p pulses and not one more. It may
 *     emit fewer only when halted, and must then report how many.
 *   - **A truthful counter.** @p emitted survives the end of the run and
 *     survives an immediate halt. It is the only physical record of how far the
 *     film moved, so a count that was right until the last interrupt is worse
 *     than useless.
 *   - **Short runs.** A run of two pulses with a long ramp is a triangle that
 *     never reaches cruise_pps, and still lands on exactly two.
 *   - **Width.** Every pulse is at least @p min_pulse_ns wide, at every rate.
 *
 * There is no completion callback. On every real backend it would fire in
 * interrupt context, which is the most portability-hostile thing an interface
 * like this can require. The control loop runs per frame, so polling state()
 * costs nothing and keeps the simulator backend trivial.
 */
typedef struct tmc2209_stepgen {
    /** Begin a run. Refuse with a negative return if one is already in flight. */
    int (*run)(void *ctx, const tmc2209_run_t *plan);

    /** Change the cruise rate of a run in flight, ramping at the plan's accel.
        Negative if nothing is running. */
    int (*retarget)(void *ctx, uint32_t cruise_pps);

    /** End the run. @p immediate cuts the train at the next pulse boundary;
        otherwise it decelerates to pullin_pps first. Either way the count stays
        readable and stays true. */
    int (*halt)(void *ctx, bool immediate);

    /** Snapshot the run. Must be atomic against whatever emits the pulses. */
    int (*state)(void *ctx, tmc2209_run_state_t *out);

    void *ctx;

    /** The fastest this peripheral can actually emit. A rate above it is
        refused rather than silently clamped: a move that ran slower than asked
        is a cadence bug, and one that ran slower than believed is a position bug. */
    uint32_t max_pps;

    /** The narrowest pulse this backend guarantees, in nanoseconds. Declared by
        the backend and checked at attach against TMC2209_STEP_MIN_PULSE_NS. */
    uint32_t min_pulse_ns;
} tmc2209_stepgen_t;

#endif /* TMC2209_STEPGEN_H */
