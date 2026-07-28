/**
 * @file rpc_raw.c
 * @brief One method per public library call, and no decisions of its own.
 *
 * Raw is a projection of `tmc2209.h` onto the wire. Every handler here decodes
 * arguments, makes exactly one library call, and encodes what came back. Where
 * a handler looks like it is deciding something, it is not: the check is one
 * the library would have made anyway, hoisted only because the frame has to be
 * rejected before a device can be named.
 *
 * A bridge, so it knows both libraries and nothing about ESP-IDF, and
 * `test/unit` compiles it against the mock driver. The paths worth testing are
 * exactly the ones a real driver will not produce on request: a corrupt CRC, a
 * silent reply, an `IFCNT` that does not advance.
 *
 * Devices are named by index into the board table. `sys.devices` is how a
 * client learns which index is which, and giving them prettier names is the
 * PC's job.
 */

#include <stddef.h>

#include "devices.h"
#include "rpc_dispatch.h"
#include "rpc_methods.h"
#include "rpc_proto.h"
#include "rpc_status.h"
#include "rpc_wire.h"
#include "tmc2209.h"
#include "watchdog.h"

/*
 * Every method starts the same way, and the order matters: the frame has to be
 * intact before an index means anything, and the index has to resolve before
 * the library can be handed a device. Returning the device or NULL keeps that
 * sequence in one place instead of at the top of twenty handlers.
 */
static tmc2209_t *dev_arg(rpc_reader_t *args)
{
    uint8_t idx = rpc_r_u8(args);
    return args->ok ? devices_at(idx) : NULL;
}

/*
 * A batch is the unit of work for both writes and bring-up: n datagrams and
 * one IFCNT check, so ten registers cost eleven transactions rather than
 * twenty. Both take the same shape on the wire, so they decode with the same
 * function.
 */
static bool ops_arg(rpc_reader_t *args, tmc2209_regval_t *ops, size_t *n)
{
    uint16_t count = rpc_r_u16(args);
    if (count == 0 || count > RPC_MAX_OPS) {
        return false;
    }

    for (uint16_t i = 0; i < count; i++) {
        ops[i].reg   = (tmc2209_reg_t)rpc_r_u8(args);
        ops[i].value = rpc_r_u32(args);
    }

    *n = count;
    return args->ok;
}

/* ── Registers ──────────────────────────────────────────────────────────── */

static rpc_status_t raw_read(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t    *dev = dev_arg(args);
    tmc2209_reg_t reg = (tmc2209_reg_t)rpc_r_u8(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint32_t      value = 0;
    tmc2209_err_t err   = tmc2209_read(dev, reg, &value);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, value);
    return RPC_OK;
}

static rpc_status_t raw_poll(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t    *dev = dev_arg(args);
    tmc2209_reg_t reg = (tmc2209_reg_t)rpc_r_u8(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint32_t      value = 0;
    tmc2209_err_t err   = tmc2209_poll_raw(dev, reg, &value);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, value);
    return RPC_OK;
}

/*
 * failed_at is diagnostic only. Any failure invalidates every slot in the
 * batch, including the ops transmitted before it, because nothing is confirmed
 * until the closing IFCNT read. So this says where the library gave up, not
 * where the state boundary is, and it travels even on success for exactly that
 * reason: it is never a boundary to act on.
 */
static rpc_status_t raw_write(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t       *dev = dev_arg(args);
    tmc2209_regval_t ops[RPC_MAX_OPS];
    size_t           n = 0;

    if (!ops_arg(args, ops, &n)) {
        return args->ok ? RPC_ARG : RPC_BAD_FRAME;
    }
    if (dev == NULL) {
        return RPC_ARG;
    }

    size_t        failed_at = 0;
    tmc2209_err_t err       = tmc2209_write(dev, ops, n, &failed_at);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u16(ret, (uint16_t)failed_at);
    return RPC_OK;
}

/* ── Conditions and verdicts ────────────────────────────────────────────── */

static rpc_status_t raw_poll_health(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint32_t      conditions = 0;
    tmc2209_err_t err        = tmc2209_poll_health(dev, &conditions);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, conditions);
    return RPC_OK;
}

static rpc_status_t raw_clear_faults(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev        = dev_arg(args);
    uint32_t   conditions = rpc_r_u32(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_clear_faults(dev, conditions));
}

/* usable travels beside the number because SG_RESULT outside the TCOOLTHRS
 * window is noise, and a control loop given only the number will act on it. */
static rpc_status_t raw_poll_load(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_load_t load = { 0 };
    tmc2209_err_t  err  = tmc2209_poll_load(dev, &load);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u16(ret, load.value);
    rpc_w_bool(ret, load.usable);
    return RPC_OK;
}

/* IOIN as it came off the wire. The PC decodes it with the same codec the
 * firmware would have used, so decoding here would only cost a round trip. */
static rpc_status_t raw_poll_pins(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint32_t      value = 0;
    tmc2209_err_t err   = tmc2209_poll_raw(dev, TMC2209_IOIN, &value);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, value);
    return RPC_OK;
}

static rpc_status_t raw_poll_version(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint8_t       version = 0;
    tmc2209_err_t err     = tmc2209_poll_version(dev, &version);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u8(ret, version);
    return RPC_OK;
}

/*
 * MISMATCH is a result, not a transport failure, and the caller wants to know
 * *which* slots disagree. But dispatch rewinds a failing reply, so the mask
 * would be discarded with it. Same shape as passthrough's outcome for the same
 * reason: what the call found travels as a value.
 */
static rpc_status_t raw_verify_config(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    uint32_t      mismatched = 0;
    tmc2209_err_t err        = tmc2209_verify_config(dev, &mismatched);
    if (err != TMC2209_OK && err != TMC2209_ERR_MISMATCH) {
        return rpc_status_of_err(err);
    }

    rpc_w_bool(ret, err == TMC2209_OK);
    rpc_w_u32(ret, mismatched);
    return RPC_OK;
}

/* ── Runtime writes ─────────────────────────────────────────────────────── */

static rpc_status_t raw_set_velocity(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev = dev_arg(args);
    int32_t    v   = rpc_r_i32(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_set_velocity(dev, v));
}

static rpc_status_t raw_set_current(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev = dev_arg(args);

    tmc2209_ihold_irun_t c = {
        .ihold      = rpc_r_u8(args),
        .irun       = rpc_r_u8(args),
        .iholddelay = rpc_r_u8(args),
    };

    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_set_current(dev, &c));
}

/* ── Bring-up and cache ─────────────────────────────────────────────────── */

/* GSTAT as found is the only look anyone gets at what the driver went through
 * before this firmware owned it, so it travels even though bring-up clears it. */
static rpc_status_t raw_bringup(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t       *dev = dev_arg(args);
    tmc2209_regval_t config[RPC_MAX_OPS];
    size_t           n = 0;

    if (!ops_arg(args, config, &n)) {
        return args->ok ? RPC_ARG : RPC_BAD_FRAME;
    }
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_gstat_t at_bringup = { 0 };
    tmc2209_err_t   err        = tmc2209_bringup(dev, config, n, &at_bringup);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, tmc2209_gstat_encode(&at_bringup));
    return RPC_OK;
}

static rpc_status_t raw_all_owned_valid(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    rpc_w_bool(ret, tmc2209_all_owned_valid(dev));
    return RPC_OK;
}

static rpc_status_t raw_invalidate_owned(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_invalidate_owned(dev);
    return RPC_OK;
}

/* ── Lines ──────────────────────────────────────────────────────────────── */

static rpc_status_t raw_line_read(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t     *dev  = dev_arg(args);
    tmc2209_line_t line = (tmc2209_line_t)rpc_r_u8(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    bool          level = false;
    tmc2209_err_t err   = tmc2209_line_read(dev, line, &level);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_bool(ret, level);
    return RPC_OK;
}

static rpc_status_t raw_line_write(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t     *dev   = dev_arg(args);
    tmc2209_line_t line  = (tmc2209_line_t)rpc_r_u8(args);
    bool           level = rpc_r_bool(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_line_write(dev, line, level));
}

static rpc_status_t raw_enable(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev = dev_arg(args);
    bool       on  = rpc_r_bool(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_enable(dev, on));
}

static rpc_status_t raw_is_enabled(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    bool          on  = false;
    tmc2209_err_t err = tmc2209_is_enabled(dev, &on);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_bool(ret, on);
    return RPC_OK;
}

/* ── Motion ─────────────────────────────────────────────────────────────── */

/*
 * The deadline is a parameter of the move and not a setting, because a setting
 * gets configured once by whoever was last debugging and then governs a scan
 * nobody was watching. 0 asks for the default; there is no value that means
 * off, which is the point.
 */
static rpc_status_t raw_move(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    uint8_t    idx = rpc_r_u8(args);
    tmc2209_t *dev = args->ok ? devices_at(idx) : NULL;

    tmc2209_move_t m = {
        .dir         = rpc_r_bool(args),
        .shaft       = rpc_r_bool(args),
        .pulses      = rpc_r_u32(args),
        .pullin_pps  = rpc_r_u32(args),
        .cruise_pps  = rpc_r_u32(args),
        .accel_pps_s = rpc_r_u32(args),
    };
    uint32_t deadline_ms = rpc_r_u32(args);

    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_err_t err = tmc2209_move(dev, &m);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    /* After the move, never before: arming a deadline for a run that was
     * refused would halt and disable a driver nobody had started. */
    watchdog_arm(idx, deadline_ms);
    return RPC_OK;
}

static rpc_status_t raw_retarget(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev        = dev_arg(args);
    uint32_t   cruise_pps = rpc_r_u32(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_retarget(dev, cruise_pps));
}

static rpc_status_t raw_halt(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)ret;

    tmc2209_t *dev       = dev_arg(args);
    bool       immediate = rpc_r_bool(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    return rpc_status_of_err(tmc2209_halt(dev, immediate));
}

static rpc_status_t raw_motion(rpc_reader_t *args, rpc_writer_t *ret)
{
    tmc2209_t *dev = dev_arg(args);
    if (dev == NULL) {
        return RPC_ARG;
    }

    tmc2209_motion_t m   = { 0 };
    tmc2209_err_t    err = tmc2209_get_motion_report(dev, &m);
    if (err != TMC2209_OK) {
        return rpc_status_of_err(err);
    }

    rpc_w_u32(ret, m.emitted);
    rpc_w_u32(ret, m.rate_pps);
    rpc_w_bool(ret, m.running);
    return RPC_OK;
}

const rpc_handler_fn rpc_raw_methods[RPC_RAW_COUNT] = {
    [RPC_RAW_READ]             = raw_read,
    [RPC_RAW_POLL]             = raw_poll,
    [RPC_RAW_WRITE]            = raw_write,
    [RPC_RAW_POLL_HEALTH]      = raw_poll_health,
    [RPC_RAW_CLEAR_FAULTS]     = raw_clear_faults,
    [RPC_RAW_POLL_LOAD]        = raw_poll_load,
    [RPC_RAW_POLL_PINS]        = raw_poll_pins,
    [RPC_RAW_POLL_VERSION]     = raw_poll_version,
    [RPC_RAW_VERIFY_CONFIG]    = raw_verify_config,
    [RPC_RAW_SET_VELOCITY]     = raw_set_velocity,
    [RPC_RAW_SET_CURRENT]      = raw_set_current,
    [RPC_RAW_BRINGUP]          = raw_bringup,
    [RPC_RAW_ALL_OWNED_VALID]  = raw_all_owned_valid,
    [RPC_RAW_INVALIDATE_OWNED] = raw_invalidate_owned,
    [RPC_RAW_LINE_READ]        = raw_line_read,
    [RPC_RAW_LINE_WRITE]       = raw_line_write,
    [RPC_RAW_ENABLE]           = raw_enable,
    [RPC_RAW_IS_ENABLED]       = raw_is_enabled,
    [RPC_RAW_MOVE]             = raw_move,
    [RPC_RAW_RETARGET]         = raw_retarget,
    [RPC_RAW_HALT]             = raw_halt,
    [RPC_RAW_MOTION]           = raw_motion,
};
