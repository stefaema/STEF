/*
 * tmc2209_stepgen.c: what a pulse source is not allowed to assume.
 *
 * A backend emits edges and counts them. It cannot know what has to hold for
 * those edges to turn the motor: DIR carrying the planned sign, GCONF.shaft
 * agreeing with it, VACTUAL at zero so the STEP pin still owns motion. Those
 * are settled here, before any backend is asked to run. The rest is refusal:
 * an impossible ramp, a rate past the backend's ceiling, or a second run over
 * one already in flight gets no further than this layer.
 */

#include "tmc2209_stepgen.h"

#include "tmc2209.h"

static tmc2209_err_t check_stepgen(const tmc2209_t *dev)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->stepgen) {
        return TMC2209_ERR_NO_BACKEND;
    }
    return TMC2209_OK;
}

/* The non-blocking and no-completion-callback nature of move() has to come with a polling
   mechanism to see the movement's state throughout the run and after It ends. */
static tmc2209_err_t poll_run_state(const tmc2209_t *dev, tmc2209_run_state_t *st)
{
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }
    /* A backend that fills only part of this then reads as zeros, not as stack. */
    st->emitted  = 0;
    st->rate_pps = 0;
    st->running  = false;
    return (dev->stepgen->state(dev->stepgen->ctx, st) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

/* GCONF.shaft inverts the phase order as well as DIR. So a move needs to configure both */
static tmc2209_err_t ensure_shaft(tmc2209_t *dev, bool shaft)
{
    uint32_t raw = 0;

    /* read the register that holds the shaft-orientation value*/
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_GCONF, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_gconf_t g = tmc2209_gconf_decode(raw);
    if (g.shaft == shaft) { /* Nothing to configure */
        return TMC2209_OK;
    }
    g.shaft = shaft;

    const tmc2209_regval_t op = { TMC2209_GCONF, tmc2209_gconf_encode(&g) };

    return tmc2209_write(dev, &op, 1, NULL);
}

/* The VACTUAL register wins over the STEP pin, so a check is needed. */
static tmc2209_err_t step_pin_is_in_charge(tmc2209_t *dev)
{
    uint32_t raw = 0;
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_VACTUAL, &raw);
    if (err == TMC2209_OK && tmc2209_vactual_decode(raw) != 0) {
        return TMC2209_ERR_ACCESS;
    }
    return TMC2209_OK;
}

/* A profile has to describe a ramp that exists. */
static tmc2209_err_t check_profile(const tmc2209_stepgen_t *sg, const tmc2209_movement_plan_t *m)
{
    if (m->pullin_pps == 0 || m->cruise_pps == 0) {
        return TMC2209_ERR_ARG;  /* a run has to start somewhere above standing still */
    }
    if (m->cruise_pps < m->pullin_pps) {
        return TMC2209_ERR_ARG;  /* cruising slower than the rate it starts at */
    }
    if (m->accel_pps_s == 0 && m->cruise_pps != m->pullin_pps) {
        return TMC2209_ERR_ARG;  /* a ramp is needed and none was allowed */
    }
    if (m->cruise_pps > sg->max_pps || m->pullin_pps > sg->max_pps) {
        return TMC2209_ERR_RATE;
    }
    return TMC2209_OK;
}

/* ── Public API ─────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_attach_stepgen(tmc2209_t *dev, const tmc2209_stepgen_t *stepgen)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    if (stepgen) {
        /* Half a backend is not a backend */
        if (!stepgen->run || !stepgen->retarget || !stepgen->halt || !stepgen->state) {
            return TMC2209_ERR_ARG;
        }
        if (stepgen->max_pps == 0) {
            return TMC2209_ERR_ARG;  /* a pulse source that cannot pulse */
        }
        /* The width is a driver's requirement */
        if (stepgen->min_pulse_ns < TMC2209_STEP_MIN_PULSE_NS) {
            return TMC2209_ERR_RATE;
        }
    }

    /* Swapping the pulse source out from under a run in flight would strand the
       count in a backend nothing points at any more. */
    if (dev->stepgen) {
        tmc2209_run_state_t st;
        tmc2209_err_t err = poll_run_state(dev, &st);
        if (err != TMC2209_OK) {
            return err;
        }
        if (st.running) {
            return TMC2209_ERR_BUSY;
        }
    }

    dev->stepgen = stepgen;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_is_running(const tmc2209_t *dev, bool *running)
{
    if (!running) {
        return TMC2209_ERR_ARG;
    }
    tmc2209_run_state_t st;
    tmc2209_err_t err = poll_run_state(dev, &st);
    if (err == TMC2209_OK) {
        *running = st.running;
    }
    return err;
}

tmc2209_err_t tmc2209_move(tmc2209_t *dev, const tmc2209_movement_plan_t *m)
{
    if (!m) {
        return TMC2209_ERR_ARG;
    }
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Check if the movement descriptor is valid */
    err = check_profile(dev->stepgen, m);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_run_state_t st;
    err = poll_run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }
    if (st.running) {
        return TMC2209_ERR_BUSY;
    }

    err = ensure_shaft(dev, m->shaft);
    if (err != TMC2209_OK) {
        return err;
    }

    err = step_pin_is_in_charge(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    /* The driver wants the DIR line settled before the first STEP comes in. */
    err = tmc2209_line_write(dev, TMC2209_LINE_DIR, m->dir);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Stepgen backend needs a subset of the movement plan: the run plan */
    const tmc2209_run_plan_t plan = {
        .pulses      = m->pulses,
        .pullin_pps  = m->pullin_pps,
        .cruise_pps  = m->cruise_pps,
        .accel_pps_s = m->accel_pps_s,
    };
    if (dev->stepgen->run(dev->stepgen->ctx, &plan) < 0) {
        return TMC2209_ERR_IO;
    }

    /* The sign of the count the backend is about to accumulate*/
    dev->run_dir   = m->dir;  /* Kept because both may change mid-run */
    dev->run_shaft = m->shaft;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_retarget(tmc2209_t *dev, uint32_t cruise_pps)
{
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }
    if (cruise_pps == 0 || cruise_pps > dev->stepgen->max_pps) {
        return TMC2209_ERR_RATE;
    }

    tmc2209_run_state_t st;
    err = poll_run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }
    if (!st.running) {
        return TMC2209_ERR_IDLE;
    }

    /* Calls the backend that supports this operation */
    return (dev->stepgen->retarget(dev->stepgen->ctx, cruise_pps) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

tmc2209_err_t tmc2209_halt(tmc2209_t *dev, bool immediate)
{
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }
    /* Call backend to halt the movement, gracefully reschedulling the negative ramp to now. */
    return (dev->stepgen->halt(dev->stepgen->ctx, immediate) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

tmc2209_err_t tmc2209_get_motion_report(tmc2209_t *dev, tmc2209_motion_report_t *out)
{
    if (!out) {
        return TMC2209_ERR_ARG;
    }

    tmc2209_run_state_t st;
    tmc2209_err_t err = poll_run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }

    out->emitted  = st.emitted;
    out->rate_pps = st.rate_pps;
    out->running  = st.running;
    out->dir      = dev->run_dir;
    out->shaft    = dev->run_shaft;
    return TMC2209_OK;
}
