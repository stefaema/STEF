/**
 * @file rpc_raw.c
 * @brief One method per public library call, and no decisions of its own.
 *
 * Raw is a projection of `tmc2209.h` onto the wire. Every handler here reads
 * its arguments as a struct, makes exactly one library call, and hands the
 * library somewhere in the reply to write. Where a handler looks like it is
 * deciding something, it is not: the check is one the library would have made
 * anyway, hoisted only because the frame has to be rejected before a device can
 * be named.
 *
 * The out-parameter is why these are short. A library call that reports an
 * error and yields its value through a pointer can be given a pointer into the
 * reply frame, so the value never exists anywhere else and there is nothing to
 * copy once the call returns. Where a handler does stage a local, it is because
 * the library's struct and the wire's are laid out differently and one of them
 * has to be translated.
 *
 * A bridge, so it knows both libraries and nothing about ESP-IDF, and
 * `test/unit` compiles it against the mock driver. The paths worth testing are
 * exactly the ones a real driver will not produce on request: a corrupt CRC, a
 * silent reply, an `IFCNT` that does not advance.
 */

#include <stddef.h>

#include "devices.h"
#include "rpc_api.h"
#include "rpc_methods.h"
#include "rpc_status.h"
#include "tmc2209.h"
#include "watchdog.h"

/*
 * A batch is the unit of work for both writes and bring-up: n datagrams and
 * one IFCNT check, so ten registers cost eleven transactions rather than
 * twenty. Both take the same shape on the wire, so they decode with the same
 * function.
 *
 * The copy is unavoidable: the library's element carries the register first and
 * the wire's carries the value first, because the wire's has to keep its
 * uint32_t aligned and the library's answers to nothing but itself.
 */
static bool ops_arg(const rpc_raw_write_args *in, size_t args_len,
                    tmc2209_regval_t *ops)
{
    if (in->count == 0 || in->count > RPC_MAX_OPS) {
        return false;
    }
    if (args_len != sizeof(*in) + (in->count * sizeof(rpc_op_t))) {
        return false;
    }

    for (uint32_t i = 0; i < in->count; i++) {
        ops[i].reg   = (tmc2209_reg_t)in->ops[i].reg;
        ops[i].value = in->ops[i].value;
    }

    return true;
}

/* ── Registers ──────────────────────────────────────────────────────────── */

static rpc_status_t raw_read(const void *args, void *ret)
{
    const rpc_raw_read_args *in  = args;
    rpc_raw_read_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_read(dev, (tmc2209_reg_t)in->reg, &out->value));
}

static rpc_status_t raw_poll(const void *args, void *ret)
{
    const rpc_raw_poll_args *in  = args;
    rpc_raw_poll_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_poll_raw(dev, (tmc2209_reg_t)in->reg, &out->value));
}

static rpc_status_t raw_write(const void *args, size_t args_len,
                              void *ret, size_t *ret_len)
{
    const rpc_raw_write_args *in  = args;
    rpc_raw_write_ret        *out = ret;

    tmc2209_regval_t ops[RPC_MAX_OPS];
    if (!ops_arg(in, args_len, ops)) {
        return RPC_BAD_FRAME;
    }

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    size_t        failed_at = 0;
    tmc2209_err_t err       = tmc2209_write(dev, ops, in->count, &failed_at);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->failed_at = (uint16_t)failed_at;

    *ret_len = sizeof(*out);
    return RPC_OK;
}

/* ── Conditions and verdicts ────────────────────────────────────────────── */

static rpc_status_t raw_poll_health(const void *args, void *ret)
{
    const rpc_raw_poll_health_args *in  = args;
    rpc_raw_poll_health_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_poll_health(dev, &out->conditions));
}

static rpc_status_t raw_clear_faults(const void *args, void *ret)
{
    const rpc_raw_clear_faults_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_clear_faults(dev, in->conditions));
}

static rpc_status_t raw_poll_load(const void *args, void *ret)
{
    const rpc_raw_poll_load_args *in  = args;
    rpc_raw_poll_load_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_load_t load = { 0 };
    tmc2209_err_t  err  = tmc2209_poll_load(dev, &load);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->value  = load.value;
    out->usable = (uint8_t)load.usable;

    return RPC_OK;
}

static rpc_status_t raw_poll_pins(const void *args, void *ret)
{
    const rpc_raw_poll_pins_args *in  = args;
    rpc_raw_poll_pins_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_poll_raw(dev, TMC2209_IOIN, &out->value));
}

static rpc_status_t raw_poll_version(const void *args, void *ret)
{
    const rpc_raw_poll_version_args *in  = args;
    rpc_raw_poll_version_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_poll_version(dev, &out->version));
}

/* MISMATCH is a result and not a transport failure, so it leaves here as
 * RPC_OK with the mask beside it. See rpc_raw_verify_config_ret. */
static rpc_status_t raw_verify_config(const void *args, void *ret)
{
    const rpc_raw_verify_config_args *in  = args;
    rpc_raw_verify_config_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_err_t err = tmc2209_verify_config(dev, &out->mismatched);
    if (err != TMC2209_OK && err != TMC2209_ERR_MISMATCH) {
        return rpc_status_of_err(err);
    }

    out->agrees = (err == TMC2209_OK) ? 1U : 0U;
    return RPC_OK;
}

/* ── Runtime writes ─────────────────────────────────────────────────────── */

static rpc_status_t raw_set_velocity(const void *args, void *ret)
{
    const rpc_raw_set_velocity_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_set_velocity(dev, in->velocity));
}

static rpc_status_t raw_set_current(const void *args, void *ret)
{
    const rpc_raw_set_current_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_ihold_irun_t c = {
        .ihold      = in->ihold,
        .irun       = in->irun,
        .iholddelay = in->iholddelay,
    };

    return rpc_status_of_err(tmc2209_set_current(dev, &c));
}

/* ── Bring-up and cache ─────────────────────────────────────────────────── */

static rpc_status_t raw_bringup(const void *args, size_t args_len,
                                void *ret, size_t *ret_len)
{
    const rpc_raw_bringup_args *in  = args;
    rpc_raw_bringup_ret        *out = ret;

    tmc2209_regval_t config[RPC_MAX_OPS];
    if (!ops_arg(in, args_len, config)) {
        return RPC_BAD_FRAME;
    }

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_gstat_t at_bringup = { false };
    tmc2209_err_t   err = tmc2209_bringup(dev, config, in->count, &at_bringup);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->gstat_at_bringup = tmc2209_gstat_encode(&at_bringup);

    *ret_len = sizeof(*out);
    return RPC_OK;
}

static rpc_status_t raw_all_owned_valid(const void *args, void *ret)
{
    const rpc_raw_all_owned_valid_args *in  = args;
    rpc_raw_all_owned_valid_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    out->valid = (uint8_t)tmc2209_all_owned_valid(dev);
    return RPC_OK;
}

static rpc_status_t raw_invalidate_owned(const void *args, void *ret)
{
    const rpc_raw_invalidate_owned_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_invalidate_owned(dev);
    return RPC_OK;
}

/* ── Lines ──────────────────────────────────────────────────────────────── */

static rpc_status_t raw_line_read(const void *args, void *ret)
{
    const rpc_raw_line_read_args *in  = args;
    rpc_raw_line_read_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    bool          level = false;
    tmc2209_err_t err   = tmc2209_line_read(dev, (tmc2209_line_t)in->line, &level);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->level = (uint8_t)level;
    return RPC_OK;
}

static rpc_status_t raw_line_write(const void *args, void *ret)
{
    const rpc_raw_line_write_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(
        tmc2209_line_write(dev, (tmc2209_line_t)in->line, in->level != 0U));
}

static rpc_status_t raw_enable(const void *args, void *ret)
{
    const rpc_raw_enable_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_enable(dev, in->on != 0U));
}

static rpc_status_t raw_is_enabled(const void *args, void *ret)
{
    const rpc_raw_is_enabled_args *in  = args;
    rpc_raw_is_enabled_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    bool          on  = false;
    tmc2209_err_t err = tmc2209_is_enabled(dev, &on);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->on = (uint8_t)on;
    return RPC_OK;
}

/* ── Motion ─────────────────────────────────────────────────────────────── */

static rpc_status_t raw_move(const void *args, void *ret)
{
    const rpc_raw_move_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_movement_plan_t m = {
        .dir         = in->dir != 0U,
        .shaft       = in->shaft != 0U,
        .pulses      = in->pulses,
        .pullin_pps  = in->pullin_pps,
        .cruise_pps  = in->cruise_pps,
        .accel_pps_s = in->accel_pps_s,
    };

    tmc2209_err_t err = tmc2209_move(dev, &m);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    /* After the move, never before: arming a deadline for a run that was
     * refused would halt and disable a driver nobody had started. */
    watchdog_arm(in->idx, in->deadline_ms);
    return RPC_OK;
}

static rpc_status_t raw_retarget(const void *args, void *ret)
{
    const rpc_raw_retarget_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_retarget(dev, in->cruise_pps));
}

static rpc_status_t raw_halt(const void *args, void *ret)
{
    const rpc_raw_halt_args *in = args;
    (void)ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_halt(dev, in->immediate != 0U));
}

static rpc_status_t raw_motion(const void *args, void *ret)
{
    const rpc_raw_motion_args *in  = args;
    rpc_raw_motion_ret        *out = ret;

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_motion_report_t m   = { 0 };
    tmc2209_err_t           err = tmc2209_get_motion_report(dev, &m);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    out->emitted  = m.emitted;
    out->rate_pps = m.rate_pps;
    out->running  = (uint8_t)m.running;
    out->dir      = (uint8_t)m.dir;
    out->shaft    = (uint8_t)m.shaft;

    return RPC_OK;
}

const rpc_method_t rpc_raw_methods[RPC_RAW_COUNT] = {
    [RPC_RAW_READ]             = RPC_METHOD(raw_read),
    [RPC_RAW_POLL]             = RPC_METHOD(raw_poll),
    [RPC_RAW_WRITE]            = RPC_METHOD_VAR(raw_write),
    [RPC_RAW_POLL_HEALTH]      = RPC_METHOD(raw_poll_health),
    [RPC_RAW_CLEAR_FAULTS]     = RPC_METHOD_ACK(raw_clear_faults),
    [RPC_RAW_POLL_LOAD]        = RPC_METHOD(raw_poll_load),
    [RPC_RAW_POLL_PINS]        = RPC_METHOD(raw_poll_pins),
    [RPC_RAW_POLL_VERSION]     = RPC_METHOD(raw_poll_version),
    [RPC_RAW_VERIFY_CONFIG]    = RPC_METHOD(raw_verify_config),
    [RPC_RAW_SET_VELOCITY]     = RPC_METHOD_ACK(raw_set_velocity),
    [RPC_RAW_SET_CURRENT]      = RPC_METHOD_ACK(raw_set_current),
    [RPC_RAW_BRINGUP]          = RPC_METHOD_VAR(raw_bringup),
    [RPC_RAW_ALL_OWNED_VALID]  = RPC_METHOD(raw_all_owned_valid),
    [RPC_RAW_INVALIDATE_OWNED] = RPC_METHOD_ACK(raw_invalidate_owned),
    [RPC_RAW_LINE_READ]        = RPC_METHOD(raw_line_read),
    [RPC_RAW_LINE_WRITE]       = RPC_METHOD_ACK(raw_line_write),
    [RPC_RAW_ENABLE]           = RPC_METHOD_ACK(raw_enable),
    [RPC_RAW_IS_ENABLED]       = RPC_METHOD(raw_is_enabled),
    [RPC_RAW_MOVE]             = RPC_METHOD_ACK(raw_move),
    [RPC_RAW_RETARGET]         = RPC_METHOD_ACK(raw_retarget),
    [RPC_RAW_HALT]             = RPC_METHOD_ACK(raw_halt),
    [RPC_RAW_MOTION]           = RPC_METHOD(raw_motion),
};
