/*
 * ramp.c: the square of the rate is linear in the pulse index, and that is the
 * whole trick.
 *
 * A ramp is defined in time, dv/dt = a, but a pulse encoder counts pulses and
 * has no clock. With dn/dt = v that becomes v dv/dn = a, so d(v²)/dn = 2a: the
 * state advances by an addition, the brake distance is one division, and only
 * the period costs a square root.
 *
 * Paying for that root every pulse is what would not fit in an interrupt. So a
 * chunk of pulses shares one period, sized so the rate never moves more than
 * 1/32 of itself inside it. Nothing is approximated by that: v² is linear, so
 * a jump of K pulses lands exactly on the ramp. Only the period is held flat
 * between two exact points.
 */

#include "ramp.h"

/* The rate may move this fraction of itself inside one chunk. */
#define RAMP_ERROR_SHIFT 5U

static uint64_t squared(uint32_t v)
{
    return (uint64_t)v * (uint64_t)v;
}

/* Newton seeded with the last rate, which is one chunk's error away, so it lands at once. */
static uint32_t rate_from_square(uint64_t v_sq, uint32_t seed)
{
    uint32_t x = (seed != 0U) ? seed : 1U;

    for (int i = 0; i < 3; i++) {
        x = (uint32_t)((x + (v_sq / x)) / 2U);
        if (x == 0U) {
            x = 1U;
        }
    }

    return x;
}

/* Move v² toward the goal by delta, never past it. */
static uint64_t toward(uint64_t v_sq, uint64_t goal_sq, uint64_t delta)
{
    if (v_sq < goal_sq) {
        v_sq += delta;
        return (v_sq > goal_sq) ? goal_sq : v_sq;
    }
    if (v_sq > goal_sq) {
        return (v_sq > goal_sq + delta) ? (v_sq - delta) : goal_sq;
    }
    return v_sq;
}

/* How many pulses may share one period, given where the ramp is and what it is heading for. */
static uint64_t chunk_len(const ramp_t *r, uint64_t goal_sq, uint64_t step, uint64_t room)
{
    uint64_t count = room;

    if (step != 0U && r->v_sq != goal_sq) {
        /* Hold the period while the rate would move by less than 1/32 of itself. */
        const uint64_t by_error = r->v_sq / (step << (RAMP_ERROR_SHIFT - 1U));

        /* And land the boundary on the goal rather than stepping past it. */
        const uint64_t diff    = (goal_sq > r->v_sq) ? (goal_sq - r->v_sq) : (r->v_sq - goal_sq);
        const uint64_t to_goal = (diff + step - 1U) / step;

        count = (by_error < to_goal) ? by_error : to_goal;
    }

    if (count > room) {
        count = room;
    }

    return (count == 0U) ? 1U : count;
}

void ramp_begin(ramp_t *r, const ramp_plan_t *plan)
{
    r->pulses           = plan->pulses;
    r->pullin_pps       = plan->pullin_pps;
    r->pullin_sq        = squared(plan->pullin_pps);
    r->accel_pps_s      = plan->accel_pps_s;
    r->resolution_hz    = plan->resolution_hz;
    r->min_period_ticks = plan->min_period_ticks;
    r->v                = plan->pullin_pps;
    r->v_sq             = r->pullin_sq;
    r->rem              = 0U;
}

void ramp_next(ramp_t *r, uint32_t index, uint32_t budget, uint32_t target_pps, bool stopping,
               ramp_chunk_t *out)
{
    /* Ramping under pull-in would leave the run unable to stop from where it is. */
    if (target_pps < r->pullin_pps) {
        target_pps = r->pullin_pps;
    }

    const uint64_t step      = 2ULL * (uint64_t)r->accel_pps_s;
    const bool     bounded   = (r->pulses != 0U);
    const uint64_t remaining = bounded ? (uint64_t)(r->pulses - index) : (uint64_t)budget;

    /* Where the down ramp starts is asked, never planned: pulses owed against what a stop costs. */
    const uint64_t brake =
        (step != 0U && r->v_sq > r->pullin_sq) ? ((r->v_sq - r->pullin_sq) / step) : 0U;

    const bool     braking = stopping || (bounded && remaining <= brake);
    const uint64_t goal_sq = braking ? r->pullin_sq : squared(target_pps);

    /* Room to the nearest thing a chunk must not step over. */
    uint64_t room = (remaining < (uint64_t)budget) ? remaining : (uint64_t)budget;
    if (!braking && bounded) {
        /* Accelerating pushes the brake point out by one pulse for every pulse
           it spends, so a chunk may only close half the gap to it. */
        uint64_t gap = remaining - brake;
        if (r->v_sq < goal_sq) {
            gap /= 2U;
        }
        if (gap < room) {
            room = gap;
        }
    }

    uint64_t count = chunk_len(r, goal_sq, step, room);

    /* A graceful halt ends the train as soon as the rate is back where it can stop. */
    if (stopping && r->v_sq <= r->pullin_sq) {
        count = 1U;
    }

    /* Sampled mid-chunk, so the staircase straddles the ramp instead of lagging behind it. */
    const uint64_t span = step * count;
    r->v                = rate_from_square(toward(r->v_sq, goal_sq, span / 2U), r->v);
    r->v_sq             = toward(r->v_sq, goal_sq, span);

    uint32_t period = r->resolution_hz / r->v;
    uint32_t frac   = r->resolution_hz - (period * r->v);
    if (period < r->min_period_ticks) {
        period = r->min_period_ticks;
        frac   = 0U;
    }

    /* The carry was taken against the previous rate, so it cannot outlive it. */
    if (r->rem >= r->v) {
        r->rem = 0U;
    }

    out->count        = (uint32_t)count;
    out->period_ticks = period;
    out->frac         = frac;
    out->rate_pps     = r->v;
    out->last         = stopping && (r->v_sq <= r->pullin_sq);
}
