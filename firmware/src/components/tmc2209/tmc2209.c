#include "tmc2209.h"
#include "tmc2209_frame.h"

#include <string.h>

#define MAX_XFER 32U   /* bounds the stack buffer used to verify passthrough echo */

/* ── Port plumbing ──────────────────────────────────────────────────────── */

static void trace(const tmc2209_bus_t *bus, bool out, const uint8_t *b, size_t n)
{
    if (bus->port->trace) {
        bus->port->trace(bus->port->ctx, out, b, n);
    }
}

static void bus_lock(const tmc2209_bus_t *bus)
{
    if (bus->port->lock) {
        bus->port->lock(bus->port->ctx);
    }
}

static void bus_unlock(const tmc2209_bus_t *bus)
{
    if (bus->port->unlock) {
        bus->port->unlock(bus->port->ctx);
    }
}

static void bus_purge(const tmc2209_bus_t *bus)
{
    if (bus->port->purge_rx) {
        bus->port->purge_rx(bus->port->ctx);
    }
}

static tmc2209_err_t port_tx(const tmc2209_bus_t *bus, const uint8_t *buf, size_t len)
{
    int n = bus->port->tx(bus->port->ctx, buf, len, bus->timeout_ms);
    trace(bus, true, buf, len);
    if (n < 0) {
        return TMC2209_ERR_IO;
    }
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_TX_TIMEOUT;
}

/* @p got reports how many bytes actually arrived, which is the difference
   between a driver that stayed silent and one that answered and was cut off.
   NULL when the caller only needs the verdict. */
static tmc2209_err_t port_rx(const tmc2209_bus_t *bus, uint8_t *buf, size_t len,
                             size_t *got)
{
    if (got) {
        *got = 0;
    }
    int n = bus->port->rx(bus->port->ctx, buf, len, bus->timeout_ms);
    if (n < 0) {
        return TMC2209_ERR_IO;
    }
    if (got) {
        *got = (size_t)n;
    }
    trace(bus, false, buf, (size_t)n);
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_RX_TIMEOUT;
}

/* Echo is evidence, not litter. Short and altered are both "not what we sent". */
static tmc2209_err_t verify_echo(const tmc2209_bus_t *bus, const uint8_t *sent, size_t len)
{
    if (!bus->port->echoes) {
        return TMC2209_OK;
    }
    if (len > MAX_XFER) {
        return TMC2209_ERR_ARG;
    }
    uint8_t echo[MAX_XFER];
    tmc2209_err_t err = port_rx(bus, echo, len, NULL);
    if (err == TMC2209_ERR_RX_TIMEOUT) {
        return TMC2209_ERR_ECHO;
    }
    if (err != TMC2209_OK) {
        return err;
    }
    return (memcmp(echo, sent, len) == 0) ? TMC2209_OK : TMC2209_ERR_ECHO;
}

/* ── Single transactions, one attempt each ──────────────────────────────── */

static tmc2209_err_t read_once(const tmc2209_bus_t *bus, uint8_t addr,
                               tmc2209_reg_t reg, uint32_t *out)
{
    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, addr, (uint8_t)reg);

    bus_purge(bus);

    tmc2209_err_t err = port_tx(bus, req, sizeof req);
    if (err != TMC2209_OK) {
        return err;
    }
    err = verify_echo(bus, req, sizeof req);
    if (err != TMC2209_OK) {
        return err;
    }

    uint8_t reply[TMC2209_REPLY_LEN];
    err = port_rx(bus, reply, sizeof reply, NULL);
    if (err != TMC2209_OK) {
        return err;
    }
    return tmc2209_frame_parse_reply(reply, (uint8_t)reg, out);
}

static tmc2209_err_t write_once(const tmc2209_bus_t *bus, uint8_t addr,
                                tmc2209_reg_t reg, uint32_t value)
{
    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, addr, (uint8_t)reg, value);

    bus_purge(bus);

    tmc2209_err_t err = port_tx(bus, dg, sizeof dg);
    if (err != TMC2209_OK) {
        return err;
    }
    return verify_echo(bus, dg, sizeof dg);
}

/* ── Single transactions, multiple attempts ──────────────────────────────── */

/* Reads have no side effect, so retrying is free.
   Writes are idempotent, so retrying is safe but may double-count IFCNT. */
static tmc2209_err_t read_retrying(const tmc2209_bus_t *bus, uint8_t addr,
                                   tmc2209_reg_t reg, uint32_t *out)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= bus->retries; attempt++) {
        err = read_once(bus, addr, reg, out);
        if (err == TMC2209_OK) {
            return TMC2209_OK;
        }
        /* Draining what is already buffered needs purge_rx, which the port need
           not supply, so a retry can read the same bytes back. */
        if (err == TMC2209_ERR_REG || err == TMC2209_ERR_ARG) {
            return err;
        }
    }
    return err;
}

static tmc2209_err_t write_retrying(const tmc2209_bus_t *bus, uint8_t addr,
                                    tmc2209_reg_t reg, uint32_t value,
                                    unsigned *issued)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= bus->retries; attempt++) {
        (*issued)++;
        err = write_once(bus, addr, reg, value);
        if (err == TMC2209_OK) {
            return TMC2209_OK;
        }
    }
    return err;
}

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
static tmc2209_err_t confirm_writes(tmc2209_t *dev,
                                    unsigned registers_written,
                                    unsigned datagrams_sent)
{
    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    uint8_t  now   = tmc2209_ifcnt_decode(raw);
    unsigned delta = (uint8_t)(now - dev->ifcnt);   /* unsigned 8-bit subtraction wraps */
    dev->ifcnt = now;

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
    unsigned datagrams_sent = 0;
    tmc2209_err_t err = write_retrying(dev->bus, dev->addr, TMC2209_GSTAT, mask,
                                       &datagrams_sent);
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

tmc2209_err_t tmc2209_attach_bus(tmc2209_t *dev, const tmc2209_bus_t *bus)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    /* Half a backend is not a backend */
    if (bus && (!bus->port || !bus->port->tx || !bus->port->rx)) {
        return TMC2209_ERR_ARG;
    }
    dev->bus = bus;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_bringup(tmc2209_t *dev,
                              const tmc2209_regval_t *config, size_t n,
                              tmc2209_gstat_t *at_bringup)
{
    if (!dev || !dev->bus || !config || n == 0) {
        return TMC2209_ERR_ARG;
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
    err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }

    /* Baseline for every later write check. Mandatory. */
    dev->ifcnt = tmc2209_ifcnt_decode(raw);

    err = read_retrying(dev->bus, dev->addr, TMC2209_GSTAT, &raw);
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
        err = read_retrying(dev->bus, dev->addr, tmc2209_reg_at(slot), &raw);
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

tmc2209_err_t tmc2209_write(tmc2209_t *dev,
                            const tmc2209_regval_t *ops, size_t n,
                            size_t *failed_at)
{
    if (!dev || !dev->bus || !ops || n == 0) {
        return TMC2209_ERR_ARG;
    }

    tmc2209_err_t err = validate_batch(ops, n);
    if (err != TMC2209_OK) {
        return err;
    }

    bus_lock(dev->bus);

    /* An invalid cache means a stale IFCNT baseline too (passthrough bumps it). Re-seed. */
    if (!tmc2209_all_owned_valid(dev)) {
        uint32_t raw = 0;
        err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
        if (err == TMC2209_OK) {
            dev->ifcnt = tmc2209_ifcnt_decode(raw);
        }
    }

    unsigned registers_written = 0;   /* lower bound on the IFCNT delta */
    unsigned datagrams_sent    = 0;   /* upper bound; retries inflate it */
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

        err = write_retrying(dev->bus, dev->addr, ops[i].reg, ops[i].value,
                             &datagrams_sent);
        if (err != TMC2209_OK) {
            stopped = i;
            break;
        }
        registers_written++;
    }

    /* One write check per batch. Keeps bus quiet, but now all batch is invalid on failure */
    if (err == TMC2209_OK && registers_written > 0) {
        err = confirm_writes(dev, registers_written, datagrams_sent);
    }

    bus_unlock(dev->bus);

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
    if (!dev || !dev->bus || !conditions) {
        return TMC2209_ERR_ARG;
    }

    uint32_t raw = 0;
    /* Two registers tell driver health: GSTAT and DRV. */
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_GSTAT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    tmc2209_gstat_t g = tmc2209_gstat_decode(raw);

    uint32_t found = 0;
    if (g.reset)   { found |= (uint32_t)TMC2209_DRIVER_RESET;  }
    if (g.drv_err) { found |= (uint32_t)TMC2209_DRIVER_FAULT; }
    if (g.uv_cp)   { found |= (uint32_t)TMC2209_UNDERVOLTAGE; }

    err = read_retrying(dev->bus, dev->addr, TMC2209_DRV_STATUS, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    tmc2209_drv_status_t s = tmc2209_drv_status_decode(raw);

    if (s.otpw) { found |= (uint32_t)TMC2209_OVERTEMP_WARNING;  }
    if (s.ot)   { found |= (uint32_t)TMC2209_OVERTEMP_SHUTDOWN; }
    if (s.stst) { found |= (uint32_t)TMC2209_STANDSTILL;        }
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
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }

    /* Only clear flags the caller knew about and that are clear-able. */
    uint32_t ack = conditions & TMC2209_CONDITIONS_LATCHED;
    if (ack == 0) {
        return TMC2209_OK;
    }

    uint32_t mask = 0;
    if (ack & (uint32_t)TMC2209_DRIVER_RESET)  { mask |= 1U << 0; }
    if (ack & (uint32_t)TMC2209_DRIVER_FAULT)  { mask |= 1U << 1; }
    if (ack & (uint32_t)TMC2209_UNDERVOLTAGE)  { mask |= 1U << 2; }

    bus_lock(dev->bus);
    tmc2209_err_t err = clear_gstat(dev, mask);
    bus_unlock(dev->bus);

    /* Cache stays invalid until owned config is written again, this just clears fault flags */
    return err;
}

tmc2209_err_t tmc2209_poll_load(tmc2209_t *dev, tmc2209_load_t *out)
{
    if (!dev || !dev->bus || !out) {
        return TMC2209_ERR_ARG;
    }

    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_SG_RESULT, &raw);
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

    out->value = (uint16_t)(raw & 0x03FFU);
    out->usable = armed;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_pins(tmc2209_t *dev, tmc2209_ioin_t *out)
{
    if (!dev || !dev->bus || !out) {
        return TMC2209_ERR_ARG;
    }
    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_IOIN, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    *out = tmc2209_ioin_decode(raw);
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_version(tmc2209_t *dev, uint8_t *version)
{
    if (!dev || !dev->bus || !version) {
        return TMC2209_ERR_ARG;
    }
    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_IOIN, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    *version = tmc2209_ioin_decode(raw).version;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_poll_raw(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
{
    if (!dev || !dev->bus || !out) {
        return TMC2209_ERR_ARG;
    }
    uint8_t access = tmc2209_reg_access(reg);
    if (access == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!(access & TMC2209_ACCESS_READ)) {
        return TMC2209_ERR_ACCESS;   /* write-only driver-side; nothing to read */
    }

    bus_lock(dev->bus);
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, reg, out);
    bus_unlock(dev->bus);

    /* Cache untouched, this is a read. */
    return err;
}

/* ── Verdicts ───────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_verify_config(tmc2209_t *dev, uint32_t *mismatched)
{
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }

    uint32_t bad = 0;
    tmc2209_err_t err = TMC2209_OK;

    bus_lock(dev->bus);
    for (int slot = 0; slot < TMC2209_REG_COUNT && err == TMC2209_OK; slot++) {
        /* Only owned registers the driver answers for; the other eight are W-O. */
        if (tmc2209_reg_class_at(slot) != TMC2209_CLASS_OWNED ||
            !(tmc2209_reg_access_at(slot) & TMC2209_ACCESS_READ)    ||
            !(dev->valid & (1U << slot))) {
            continue;
        }
        uint32_t raw = 0;
        err = read_retrying(dev->bus, dev->addr, tmc2209_reg_at(slot), &raw);
        if (err == TMC2209_OK && raw != dev->cache[slot]) {
            bad |= (1U << slot);
        }
    }
    bus_unlock(dev->bus);

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

/* ── Passthrough ────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_bus_send(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len, size_t *rx_got)
{
    if (rx_got) {
        *rx_got = 0;
    }
    if (!bus || !bus->port || !tx || tx_len == 0 || tx_len > MAX_XFER) {
        return TMC2209_ERR_ARG;
    }
    if (rx_len > 0 && !rx) {
        return TMC2209_ERR_ARG;
    }

    bus_lock(bus);
    bus_purge(bus);

    tmc2209_err_t err = port_tx(bus, tx, tx_len);
    if (err == TMC2209_OK) {
        err = verify_echo(bus, tx, tx_len);
    }

    /* A collision does not stop the driver from answering, and whether it did
       is exactly what a diagnostic is asking. So the reply is collected even
       after a bad echo, and the echo verdict survives as the return value
       because it names the earlier and more specific fault. */
    if ((err == TMC2209_OK || err == TMC2209_ERR_ECHO) && rx_len > 0) {
        size_t got = 0;
        tmc2209_err_t reply_err = port_rx(bus, rx, rx_len, &got);
        if (rx_got) {
            *rx_got = got;
        }
        if (err == TMC2209_OK) {
            err = reply_err;
        }
    }

    bus_unlock(bus);
    return err;
}
