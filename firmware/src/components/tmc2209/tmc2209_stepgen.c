/*
 * tmc2209_stepgen.c: the driver facts a pulse source does not have.
 *
 * The backend emits edges and counts them. What it cannot know is what has to
 * be true for those edges to move the motor: that DIR is settled and stays
 * settled, that GCONF.shaft is the one the move was planned around, and that a
 * non-zero VACTUAL has not quietly taken the driver off its STEP pin.
 *
 * Same division as tmc2209_enable(), which exists so that no caller has to
 * remember ENN is active low. A backend that knew any of this would have to be
 * rewritten for every board.
 *
 * What is deliberately absent is an odometer. A count of pulses becomes a
 * position only once someone decides which direction was positive and what a
 * pulse is worth in millimetres, and neither is knowable here. So a run's count
 * is reported and the accumulating is somebody else's.
 */

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

/* Every question about a run goes through the backend, never through a
   remembered answer: the pulses stop on their own schedule and nothing here
   is told when. */
static tmc2209_err_t run_state(const tmc2209_t *dev, tmc2209_run_state_t *st)
{
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }
    st->emitted  = 0;
    st->rate_pps = 0;
    st->running  = false;
    return (dev->stepgen->state(dev->stepgen->ctx, st) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

/* GCONF.shaft inverts the phase order, so a level on DIR only means something
   once paired with a shaft bit. The move states both and this makes the second
   one true, which costs a datagram exactly when the driver holds the other
   value and nothing at all when it already agrees.

   The bit position stays in tmc2209_reg.c: this decodes, sets and re-encodes
   rather than masking a 3 into a register in a second file.

   An invalid slot is a real answer here. GCONF's other bits would have to be
   invented to build the new value, and inventing configuration is worse than
   refusing to move. */
static tmc2209_err_t ensure_shaft(tmc2209_t *dev, bool shaft)
{
    uint32_t raw = 0;
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_GCONF, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_gconf_t g = tmc2209_gconf_decode(raw);
    if (g.shaft == shaft) {
        return TMC2209_OK;
    }
    g.shaft = shaft;

    const tmc2209_regval_t op = { TMC2209_GCONF, tmc2209_gconf_encode(&g) };
    return tmc2209_write(dev, &op, 1, NULL);
}

/* The internal velocity generator wins over the STEP pin, silently and with no
   fault raised, so a move made under it would count pulses that turned nothing.
   Checked only when the cache can answer: an invalid slot means the velocity is
   unknown, and a refusal manufactured from ignorance is worse than no check. */
static tmc2209_err_t step_pin_is_in_charge(tmc2209_t *dev)
{
    uint32_t raw = 0;
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_VACTUAL, &raw);
    if (err == TMC2209_OK && tmc2209_vactual_decode(raw) != 0) {
        return TMC2209_ERR_ACCESS;
    }
    return TMC2209_OK;
}

/* A profile has to describe a ramp that exists. Every rejection here is a
   contradiction in the request rather than a limit of the hardware, which is
   what separates these from TMC2209_ERR_RATE. */
static tmc2209_err_t check_profile(const tmc2209_stepgen_t *sg, const tmc2209_move_t *m)
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
        /* The width is the part's requirement, so it is checked here and not
           left for a backend to know about a chip it has never heard of. */
        if (stepgen->min_pulse_ns < TMC2209_STEP_MIN_PULSE_NS) {
            return TMC2209_ERR_RATE;
        }
    }

    /* Swapping the pulse source out from under a run in flight would strand the
       count in a backend nothing points at any more. */
    if (dev->stepgen) {
        tmc2209_run_state_t st;
        tmc2209_err_t err = run_state(dev, &st);
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
    tmc2209_err_t err = run_state(dev, &st);
    if (err == TMC2209_OK) {
        *running = st.running;
    }
    return err;
}

tmc2209_err_t tmc2209_move(tmc2209_t *dev, const tmc2209_move_t *m)
{
    if (!m) {
        return TMC2209_ERR_ARG;
    }
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Everything the request alone can be judged on, before any state is
       consulted and long before a pin moves. */
    err = check_profile(dev->stepgen, m);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_run_state_t st;
    err = run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }
    if (st.running) {
        return TMC2209_ERR_BUSY;
    }
    /* The backend holds one run's count. Starting another would overwrite a
       total nobody has seen, and those pulses went into film. */
    if (dev->count_unread) {
        return TMC2209_ERR_UNREAD;
    }

    err = ensure_shaft(dev, m->shaft);
    if (err != TMC2209_OK) {
        return err;
    }

    err = step_pin_is_in_charge(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    /* DIR first, always. The part wants it settled before the first STEP edge,
       and a backend that starts a pulse faster than that setup time is the one
       place a delay belongs. From here until the run ends, tmc2209_line_write()
       will not let it move again. */
    err = tmc2209_line_write(dev, TMC2209_LINE_DIR, m->dir);
    if (err != TMC2209_OK) {
        return err;
    }

    const tmc2209_run_t plan = {
        .pulses      = m->pulses,
        .pullin_pps  = m->pullin_pps,
        .cruise_pps  = m->cruise_pps,
        .accel_pps_s = m->accel_pps_s,
    };
    if (dev->stepgen->run(dev->stepgen->ctx, &plan) < 0) {
        return TMC2209_ERR_IO;
    }

    dev->count_unread = true;
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
    err = run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }
    if (!st.running) {
        return TMC2209_ERR_IDLE;
    }

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
    /* The count is left owed: a ramped halt is still emitting when this
       returns, so its total is not known yet and collecting it now would
       collect it short. */
    return (dev->stepgen->halt(dev->stepgen->ctx, immediate) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

tmc2209_err_t tmc2209_get_motion_report(tmc2209_t *dev, tmc2209_motion_t *out)
{
    if (!out) {
        return TMC2209_ERR_ARG;
    }

    tmc2209_run_state_t st;
    tmc2209_err_t err = run_state(dev, &st);
    if (err != TMC2209_OK) {
        return err;
    }

    out->emitted  = st.emitted;
    out->rate_pps = st.rate_pps;
    out->running  = st.running;

    /* A total the caller now holds is a total that will not be lost when the
       next run overwrites it. Mid-run there is no total yet, so the debt
       stands. */
    if (!st.running) {
        dev->count_unread = false;
    }
    return TMC2209_OK;
}
