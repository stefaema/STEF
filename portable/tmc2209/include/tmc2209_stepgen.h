/*
 * tmc2209_stepgen.h: STEP as a rate, not a level.
 *
 * A pulse train cannot be stateless nor blocking.
 *
 * So this is a backend interface that lets connect timer-based behaviour.
 * It emits edges on a pin and counts them. It knows nothing of DIR,
 * GCONF.shaft or microstep resolution, so the count here is in pulses and
 * becomes microsteps one layer up, where CHOPCONF.mres is cached.
 *
 * Rates are pulses per second (pps). A full step holds up to 256 pulses.
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
 * Three rates, to avoid commanding a stepper faster than it can accelerate,
 * which makes it slip and move an unknown distance.
 */
typedef struct {
    uint32_t pulses;       /**< STEP edges to emit. 0 runs until halted */
    uint32_t pullin_pps;   /**< rate of the first and last pulse: the fastest this
                                motor and load can start and stop at while
                                staying in sync */
    uint32_t cruise_pps;   /**< rate held between the ramps. A run too short to
                                finish accelerating never reaches it, and the
                                profile becomes a triangle */
    uint32_t accel_pps_s;  /**< slope of both ramps. 0 means no ramp at all, which
                                is only coherent when cruise_pps == pullin_pps */
} tmc2209_run_plan_t;

/** @brief A snapshot of a run. Safe to take while one is in flight. */
typedef struct {
    uint32_t emitted;   /**< pulses since this run began. See the note below */
    uint32_t rate_pps;  /**< the rate presently being emitted */
    bool     pulsing;   /**< false once the last pulse is out, or once halted */
} tmc2209_run_state_t;

/**
 * @brief A source of pulses on one driver's STEP pin. One per driver.
 *
 * Every call reports failure as a plain int, as the port and the lines do.
 *
 * What an implementation must guarantee:
 *
 *   - **Exact counts.** A bounded run emits @p pulses and not one more. It may
 *     emit fewer only when halted, and must then report how many.
 *   - **A correct counter.** @p emitted survives the end of the run and an
 *     immediate halt. It is the only record of how far the motor went.
 *   - **Short runs.** A run of few pulses with a long ramp is a triangle that
 *     never reaches cruise_pps, so the amount of steps is prioritized over rate.
 *   - **Width.** Every pulse is at least @p min_pulse_ns wide, at every rate.
 *
 * There is no completion callback.
 */
typedef struct tmc2209_stepgen {
    /** Begin a run. Refuse with a negative return if one is already in flight. */
    int (*run)(void *ctx, const tmc2209_run_plan_t *plan);

    /** Change the cruise rate of a run in flight, ramping at the plan's accel.
        Negative if nothing is running. */
    int (*retarget)(void *ctx, uint32_t cruise_pps);

    /** End the run. @p immediate cuts the train at the next pulse boundary;
        otherwise it decelerates to pullin_pps first. Either way the count stays
        readable and correct. */
    int (*halt)(void *ctx, bool immediate);

    /** Snapshot the run. Fills every field, atomically against whatever emits
        the pulses. */
    int (*state)(void *ctx, tmc2209_run_state_t *out);

    void *ctx;

    /** The fastest this peripheral can actually emit. A rate above it is
        refused, to avoid a move running slower than believed. */
    uint32_t max_pps;

    /** The slowest this peripheral can emit. A rate below it is refused. */
    uint32_t min_pps;

    /** The narrowest pulse this backend guarantees, in nanoseconds. Declared by
        the backend and checked at attach against TMC2209_STEP_MIN_PULSE_NS. */
    uint32_t min_pulse_ns;
} tmc2209_stepgen_t;

#endif /* TMC2209_STEPGEN_H */
