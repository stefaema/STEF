/*
 * tmc2209.c: the device itself, meaning lifecycle, registers and the cache.
 *
 * Everything here is a question about what the driver holds rather than about
 * how bytes reach it. A transaction is one call away, in tmc2209_uart_priv.h,
 * and what this file adds on top is the part a datagram cannot answer alone:
 * whether a write landed, whether a remembered value is still true, and which
 * registers a caller is allowed to ask about at all.
 */

#include "tmc2209.h"
#include "tmc2209_uart_priv.h"

#include <string.h>

/* ── Cache bookkeeping ──────────────────────────────────────────────────── */

/* Derived from the table, so adding a register cannot leave the two disagreeing. */
static uint32_t owned_mask(void)
{
    uint32_t mask = 0;
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_OWNED) {
            mask |= (1U << slot);
        }
    }
    return mask;
}

static void mark_valid(tmc2209_t *dev, int slot, uint32_t value)
{
    dev->cache[slot] = value;
    dev->valid |= (1U << slot);
}

/* ── IFCNT verification ─────────────────────────────────────────────────── */

/* Writes get no reply, so IFCNT is the only acknowledgement that exists.
   A range, not an exact delta: a retried write may have been counted twice.
   Reads do not advance IFCNT, so retrying this read cannot skew what it checks. */
static tmc2209_err_t confirm_writes(tmc2209_t *dev, unsigned registers_written,
                                    unsigned datagrams_sent)
{
    uint32_t      raw = 0;
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    uint8_t  now   = tmc2209_ifcnt_decode(raw);
    unsigned delta = (uint8_t)(now - dev->ifcnt);   /* unsigned 8-bit subtraction wraps */
    dev->ifcnt     = now;

    if (delta < registers_written || delta > datagrams_sent) {
        return TMC2209_ERR_NO_ACK;
    }
    return TMC2209_OK;
}

/* GSTAT is volatile, so this goes around tmc2209_write(): clearing latched
   flags is not configuration. Write-1-to-clear, so only the bits in @p mask go.  */
static tmc2209_err_t clear_gstat(tmc2209_t *dev, uint32_t mask)
{
    if (mask == 0) {
        return TMC2209_OK;
    }
    unsigned      datagrams_sent = 0;
    tmc2209_err_t err =
        tmc2209_uart_write_reg(dev->uart, dev->addr, TMC2209_GSTAT, mask, &datagrams_sent);
    if (err != TMC2209_OK) {
        return err;
    }
    return confirm_writes(dev, 1, datagrams_sent);
}

/* ── Batch write ────────────────────────────────────────────────────────── */

/* Makes sure all registers in a write batch are valid and readable */
static tmc2209_err_t validate_batch(const tmc2209_regval_t *ops, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (tmc2209_reg_slot(ops[i].reg) < 0) {
            return TMC2209_ERR_ARG;
        }
        if (tmc2209_reg_class(ops[i].reg) != TMC2209_CLASS_OWNED) {
            return TMC2209_ERR_ACCESS;
        }
    }
    return TMC2209_OK;
}

/* True when a later op targets the same register (thus it will have no effect after batch completes).
 @p at indexes @p ops. */
static bool superseded(const tmc2209_regval_t *ops, size_t count, size_t at)
{
    for (size_t later = at + 1; later < count; later++) {
        if (ops[later].reg == ops[at].reg) {
            return true;
        }
    }
    return false;
}

static void invalidate_batch(tmc2209_t *dev, const tmc2209_regval_t *ops, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        int slot = tmc2209_reg_slot(ops[i].reg);
        if (slot >= 0) {
            dev->valid &= ~(1U << slot);
        }
    }
}

/* ── Public API ─────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_init(tmc2209_t *dev, uint8_t addr)
{
    if (!dev || addr > 3) {
        return TMC2209_ERR_ARG;
    }
    memset(dev, 0, sizeof *dev);
    dev->addr = addr;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_bringup(tmc2209_t *dev, const tmc2209_regval_t *config, size_t n,
                              tmc2209_gstat_t *at_bringup)
{
    if (!dev || !config || n == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    tmc2209_err_t err = validate_batch(config, n);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Every OWNED register must be configured at bring-up. */
    uint32_t covered = 0;
    for (size_t i = 0; i < n; i++) {
        if (config[i].reg == TMC2209_VACTUAL && config[i].value != 0) {
            return TMC2209_ERR_ARG; /* A non-zero value on VACTUAL is dangerous */
        }
        covered |= (1U << tmc2209_reg_slot(config[i].reg));
    }
    if (covered != owned_mask()) {
        return TMC2209_ERR_ARG;
    }

    uint32_t raw = 0;

    /* Fail fast if driver isn't reachable: OK means framing, addressing and wiring work. */
    err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Baseline for every later write check. Mandatory. */
    dev->ifcnt = tmc2209_ifcnt_decode(raw);

    err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_GSTAT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Only chance to see these flags: the clear below discards them. */
    if (at_bringup) {
        *at_bringup = tmc2209_gstat_decode(raw);
    }

    /* Bring-up starts from clean flags; raw is already the mask of what was seen. */
    err = clear_gstat(dev, raw);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Constant registers are only read at bring-up as they don't practically change. */
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) != TMC2209_CLASS_CONSTANT) {
            continue;
        }
        err = tmc2209_uart_read_reg(dev->uart, dev->addr, tmc2209_reg_at(slot), &raw);
        if (err != TMC2209_OK) {
            return err;
        }
        mark_valid(dev, slot, raw);
    }

    /* Bring-up is after-init setup = group write of initial config. */
    return tmc2209_write(dev, config, n, NULL);
}

tmc2209_err_t tmc2209_read(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
{
    if (!dev || !out) {
        return TMC2209_ERR_ARG;
    }
    int slot = tmc2209_reg_slot(reg);
    if (slot < 0) {
        return TMC2209_ERR_ARG;
    }
    /* Volatile regs are uncachable as a delayed read is stale by definition. */
    if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_VOLATILE) {
        return TMC2209_ERR_ACCESS; /* You poll volatiles, you don't read them. */
    }
    if (!(dev->valid & (1U << slot))) {
        return TMC2209_ERR_INVALID_SLOT;
    }
    *out = dev->cache[slot];
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_write(tmc2209_t *dev, const tmc2209_regval_t *ops, size_t n,
                            size_t *failed_at)
{
    if (!dev || !ops || n == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    tmc2209_err_t err = validate_batch(ops, n);
    if (err != TMC2209_OK) {
        return err;
    }

    tmc2209_uart_lock(dev->uart);

    /* An invalid cache means a stale IFCNT baseline too (passthrough bumps it). Re-seed. */
    if (!tmc2209_all_owned_valid(dev)) {
        uint32_t raw = 0;
        err          = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_IFCNT, &raw);
        if (err == TMC2209_OK) {
            dev->ifcnt = tmc2209_ifcnt_decode(raw);
        }
    }

    unsigned registers_written = 0; /* lower bound on the IFCNT delta */
    unsigned datagrams_sent    = 0; /* upper bound; retries inflate it */
    size_t   stopped           = n;

    for (size_t i = 0; i < n && err == TMC2209_OK; i++) {
        int slot = tmc2209_reg_slot(ops[i].reg);

        /* Ignore if later op in the batch overwrites same register. */
        if (superseded(ops, n, i)) {
            continue;
        }
        /* Already on the device; sending it again buys nothing. */
        if ((dev->valid & (1U << slot)) && dev->cache[slot] == ops[i].value) {
            continue;
        }

        err =
            tmc2209_uart_write_reg(dev->uart, dev->addr, ops[i].reg, ops[i].value, &datagrams_sent);
        if (err != TMC2209_OK) {
            stopped = i;
            break;
        }
        registers_written++;
    }

    /* One write check per batch. Keeps the wire quiet, but now all batch is invalid on failure */
    if (err == TMC2209_OK && registers_written > 0) {
        err = confirm_writes(dev, registers_written, datagrams_sent);
    }

    tmc2209_uart_unlock(dev->uart);

    if (failed_at) {
        *failed_at = stopped;
    }

    if (err != TMC2209_OK) {
        invalidate_batch(dev, ops, n);
        return err;
    }

    for (size_t i = 0; i < n; i++) {
        mark_valid(dev, tmc2209_reg_slot(ops[i].reg), ops[i].value);
    }
    return TMC2209_OK;
}

/* ── Conditions ─────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_poll_health(tmc2209_t *dev, uint32_t *conditions)
{
    if (!dev || !conditions) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    uint32_t      raw = 0;
    /* Two registers tell driver health: GSTAT and DRV. */
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_GSTAT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    tmc2209_gstat_t g = tmc2209_gstat_decode(raw);

    uint32_t found = 0;
    if (g.reset) {
        found |= (uint32_t)TMC2209_DRIVER_RESET;
    }
    if (g.drv_err) {
        found |= (uint32_t)TMC2209_DRIVER_FAULT;
    }
    if (g.uv_cp) {
        found |= (uint32_t)TMC2209_UNDERVOLTAGE;
    }

    err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_DRV_STATUS, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    tmc2209_drv_status_t s = tmc2209_drv_status_decode(raw);

    if (s.otpw) {
        found |= (uint32_t)TMC2209_OVERTEMP_WARNING;
    }
    if (s.ot) {
        found |= (uint32_t)TMC2209_OVERTEMP_SHUTDOWN;
    }
    if (s.stst) {
        found |= (uint32_t)TMC2209_STANDSTILL;
    }
    if (s.s2ga || s.s2gb || s.s2vsa || s.s2vsb) {
        found |= (uint32_t)TMC2209_SHORT_CIRCUIT;
    }
    /* Reported, but not a fault: reads true at standstill and at low current. */
    if (s.ola || s.olb) {
        found |= (uint32_t)TMC2209_OPEN_LOAD;
    }

    /* Driver came up holding defaults. Caller re-sends its configuration. */
    if ((found & (uint32_t)TMC2209_DRIVER_RESET) != 0) {
        tmc2209_invalidate_owned(dev);
    }

    *conditions = found;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_clear_faults(tmc2209_t *dev, uint32_t conditions)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    /* Only clear flags the caller knew about and that are clear-able. */
    uint32_t ack = conditions & TMC2209_CONDITIONS_LATCHED;
    if (ack == 0) {
        return TMC2209_OK;
    }

    uint32_t mask = 0;
    if (ack & (uint32_t)TMC2209_DRIVER_RESET) {
        mask |= 1U << 0;
    }
    if (ack & (uint32_t)TMC2209_DRIVER_FAULT) {
        mask |= 1U << 1;
    }
    if (ack & (uint32_t)TMC2209_UNDERVOLTAGE) {
        mask |= 1U << 2;
    }

    tmc2209_uart_lock(dev->uart);
    tmc2209_err_t err = clear_gstat(dev, mask);
    tmc2209_uart_unlock(dev->uart);

    /* Cache stays invalid until owned config is written again, this just clears fault flags */
    return err;
}

tmc2209_err_t tmc2209_poll_load(tmc2209_t *dev, tmc2209_load_t *out)
{
    if (!dev || !out) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    uint32_t      raw = 0;
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_SG_RESULT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    uint32_t tcoolthrs = 0;
    bool     armed     = false;
    /* Zero TCOOLTHRS means StallGuard is off, so SG_RESULT is invalid. */
    /* An unknown TCOOLTHRS is treated the same way. than if 0 */
    if (tmc2209_read(dev, TMC2209_TCOOLTHRS, &tcoolthrs) == TMC2209_OK) {
        armed = (tcoolthrs != 0);
    }

    out->value  = (uint16_t)(raw & 0x03FFU);
    out->usable = armed;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_pins(tmc2209_t *dev, tmc2209_ioin_t *out)
{
    if (!dev || !out) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }
    uint32_t      raw = 0;
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_IOIN, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    *out = tmc2209_ioin_decode(raw);
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_version(tmc2209_t *dev, uint8_t *version)
{
    if (!dev || !version) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }
    uint32_t      raw = 0;
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, TMC2209_IOIN, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    *version = tmc2209_ioin_decode(raw).version;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_raw(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
{
    if (!dev || !out) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }
    uint8_t access = tmc2209_reg_access(reg);
    if (access == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!(access & TMC2209_ACCESS_READ)) {
        return TMC2209_ERR_ACCESS; /* write-only driver-side; nothing to read */
    }

    tmc2209_uart_lock(dev->uart);
    tmc2209_err_t err = tmc2209_uart_read_reg(dev->uart, dev->addr, reg, out);
    tmc2209_uart_unlock(dev->uart);

    /* Cache untouched, this is a read. */
    return err;
}

/* ── Verdicts ───────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_verify_config(tmc2209_t *dev, uint32_t *mismatched)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->uart) {
        return TMC2209_ERR_NO_BACKEND;
    }

    uint32_t      bad = 0;
    tmc2209_err_t err = TMC2209_OK;

    tmc2209_uart_lock(dev->uart);
    for (int slot = 0; slot < TMC2209_REG_COUNT && err == TMC2209_OK; slot++) {
        /* Only owned registers the driver answers for; the other eight are W-O. */
        if (tmc2209_reg_class_at(slot) != TMC2209_CLASS_OWNED ||
            !(tmc2209_reg_access_at(slot) & TMC2209_ACCESS_READ) || !(dev->valid & (1U << slot))) {
            continue;
        }
        uint32_t raw = 0;
        err          = tmc2209_uart_read_reg(dev->uart, dev->addr, tmc2209_reg_at(slot), &raw);
        if (err == TMC2209_OK && raw != dev->cache[slot]) {
            bad |= (1U << slot);
        }
    }
    tmc2209_uart_unlock(dev->uart);

    if (mismatched) {
        *mismatched = bad;
    }
    if (err != TMC2209_OK) {
        return err;
    }
    return (bad == 0) ? TMC2209_OK : TMC2209_ERR_MISMATCH;
}

/* ── Runtime writes ─────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_set_velocity(tmc2209_t *dev, int32_t v)
{
    const tmc2209_regval_t op = { TMC2209_VACTUAL, tmc2209_vactual_encode(v) };
    return tmc2209_write(dev, &op, 1, NULL);
}

tmc2209_err_t tmc2209_set_current(tmc2209_t *dev, const tmc2209_ihold_irun_t *c)
{
    if (!c) {
        return TMC2209_ERR_ARG;
    }
    const tmc2209_regval_t op = { TMC2209_IHOLD_IRUN, tmc2209_ihold_irun_encode(c) };
    return tmc2209_write(dev, &op, 1, NULL);
}

/* ── Cache validity ─────────────────────────────────────────────────────── */

bool tmc2209_all_owned_valid(const tmc2209_t *dev)
{
    if (!dev) {
        return false;
    }
    uint32_t owned = owned_mask();
    return (dev->valid & owned) == owned;
}

void tmc2209_invalidate_owned(tmc2209_t *dev)
{
    if (dev) {
        dev->valid &= ~owned_mask();
    }
}
