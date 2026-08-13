/*
 * ramp.h: what rate the next pulses carry, decided a chunk at a time.
 *
 * Freestanding on purpose. No ESP-IDF here, so the arithmetic that decides
 * where a run brakes is compiled and tested on the host, where a wrong brake
 * point is a failed assertion instead of a motor that arrives out of step.
 */

#ifndef RAMP_H
#define RAMP_H

#include <stdbool.h>
#include <stdint.h>

/** @brief A run, in the units the pulse encoder works in. */
typedef struct {
    uint32_t pulses;           /**< 0 runs until halted */
    uint32_t pullin_pps;       /**< rate of the first and last pulse */
    uint32_t accel_pps_s;      /**< slope of both ramps. 0 means no ramp */
    uint32_t resolution_hz;    /**< ticks per second the periods are counted in */
    uint32_t min_period_ticks; /**< shortest period the caller can encode */
} ramp_plan_t;

/** @brief One period, and how many pulses may carry it before the rate is asked again. */
typedef struct {
    uint32_t count;
    uint32_t period_ticks;
    uint32_t frac;     /**< ticks owed per pulse, over @c rate_pps */
    uint32_t rate_pps; /**< the rate this chunk was sampled at */
    bool     last;     /**< a graceful halt has reached pull-in: the run ends here */
} ramp_chunk_t;

typedef struct {
    uint64_t v_sq;
    uint64_t pullin_sq;
    uint32_t v;
    uint32_t rem;
    uint32_t pullin_pps;
    uint32_t accel_pps_s;
    uint32_t pulses;
    uint32_t resolution_hz;
    uint32_t min_period_ticks;
} ramp_t;

/** @brief Arm a run at its pull-in rate. */
void ramp_begin(ramp_t *r, const ramp_plan_t *plan);

/**
 * @brief The next chunk, never longer than @p budget pulses.
 *
 * @p target_pps and @p stopping are passed rather than stored because they are
 * written by whoever commands the run and read here, wherever "here" runs.
 */
void ramp_next(ramp_t *r, uint32_t index, uint32_t budget, uint32_t target_pps, bool stopping,
               ramp_chunk_t *out);

/** @brief The next pulse of a chunk, carrying the fractional tick rather than dropping it. */
static inline uint32_t ramp_period(ramp_t *r, const ramp_chunk_t *c)
{
    uint32_t period = c->period_ticks;

    r->rem += c->frac;
    if (r->rem >= c->rate_pps) {
        r->rem -= c->rate_pps;
        period++;
    }

    return period;
}

#endif /* RAMP_H */
