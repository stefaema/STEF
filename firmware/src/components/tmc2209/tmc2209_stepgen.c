/*
 * tmc2209_stepgen.c: the driver facts a pulse source does not have.
 *
 * The backend emits edges and counts them. Everything that makes those edges
 * mean something lives here: which DIR level winds film forward once
 * GCONF.shaft has had its say, that a non-zero VACTUAL has quietly taken the
 * driver off its STEP pin, and that a count of pulses only becomes a position
 * once it carries a sign.
 *
 * Same division as tmc2209_enable(), which exists so that no caller has to
 * remember ENN is active low. A backend that knew any of this would have to be
 * rewritten for every board.
 */

#include "tmc2209.h"

/* A run's pulses fold into position when the run ends, and a run that ends is
   one that state() reported as no longer running. Every entry point that could
   observe or disturb the odometer goes through here first. */
static tmc2209_err_t settle(tmc2209_t *dev, tmc2209_motion_t *out);

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

/* Direction is a sign on the odometer, not a property of the count. Keeping the
   odometer in forward pulses rather than in DIR levels is what makes it survive
   a board that wires DIR inverted or a GCONF.shaft written mid-scan. */
static int32_t signed_pulses(bool forward, uint32_t emitted)
{
    /* A single run of over 2^31 pulses overflows. At any rate this machine can
       use that is days of continuous motion in one direction without a stop. */
    int32_t n = (int32_t)emitted;
    return forward ? n : -n;
}

/* GCONF.shaft inverts the phase order, so the level that winds film forward is
   a configuration question and not a wiring one. An invalid slot is a real
   answer here: nothing knows which way this driver would turn. */
static tmc2209_err_t forward_level(tmc2209_t *dev, bool forward, bool *level)
{
    uint32_t raw = 0;
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_GCONF, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    *level = (forward != tmc2209_gconf_decode(raw).shaft);
    return TMC2209_OK;
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
        tmc2209_motion_t motion;
        tmc2209_err_t err = settle(dev, &motion);
        if (err != TMC2209_OK) {
            return err;
        }
        if (motion.running) {
            return TMC2209_ERR_BUSY;
        }
    }

    dev->stepgen = stepgen;
    return TMC2209_OK;
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

    tmc2209_motion_t motion;
    err = settle(dev, &motion);
    if (err != TMC2209_OK) {
        return err;
    }
    if (motion.running) {
        return TMC2209_ERR_BUSY;
    }

    bool level = false;
    err = forward_level(dev, m->forward, &level);
    if (err != TMC2209_OK) {
        return err;
    }

    err = step_pin_is_in_charge(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    /* DIR first, always. The part wants it settled before the first STEP edge,
       and a backend that starts a pulse faster than that setup time is the one
       place a delay belongs. */
    err = tmc2209_line_write(dev, TMC2209_LINE_DIR, level);
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

    dev->run_forward = m->forward;
    dev->run_pending = true;
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

    tmc2209_motion_t motion;
    err = settle(dev, &motion);
    if (err != TMC2209_OK) {
        return err;
    }
    if (!motion.running) {
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
    /* No settling: a ramped halt is still emitting when this returns, so the
       final count is not known yet and folding it now would fold it short. */
    return (dev->stepgen->halt(dev->stepgen->ctx, immediate) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

tmc2209_err_t tmc2209_motion(tmc2209_t *dev, tmc2209_motion_t *out)
{
    if (!out) {
        return TMC2209_ERR_ARG;
    }
    return settle(dev, out);
}

tmc2209_err_t tmc2209_zero_position(tmc2209_t *dev)
{
    tmc2209_motion_t motion;
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }
    err = settle(dev, &motion);
    if (err != TMC2209_OK) {
        return err;
    }
    if (motion.running) {
        return TMC2209_ERR_BUSY;
    }

    dev->position = 0;
    return TMC2209_OK;
}

/* ── Settling ───────────────────────────────────────────────────────────── */

static tmc2209_err_t settle(tmc2209_t *dev, tmc2209_motion_t *out)
{
    tmc2209_err_t err = check_stepgen(dev);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_run_state_t st = { 0, 0, false };
    if (dev->stepgen->state(dev->stepgen->ctx, &st) < 0) {
        return TMC2209_ERR_IO;
    }

    /* In flight, the pulses so far are real but not final, so they are reported
       without being committed. Once the run ends they are committed exactly
       once, which is what run_pending tracks: state() keeps reporting the last
       run's count forever, and adding it on every poll would be a position that
       grows while the motor stands still. */
    int32_t travelled = 0;
    if (dev->run_pending) {
        travelled = signed_pulses(dev->run_forward, st.emitted);
        if (!st.running) {
            dev->position += travelled;
            dev->run_pending = false;
            travelled = 0;
        }
    }

    out->position = dev->position + travelled;
    out->emitted  = st.emitted;
    out->rate_pps = st.rate_pps;
    out->running  = st.running;
    return TMC2209_OK;
}
