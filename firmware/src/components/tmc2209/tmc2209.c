#include "tmc2209.h"
#include "tmc2209_frame.h"

#include <string.h>

#define MAX_XFER 32u   /* bounds the stack buffer used to verify passthrough echo */

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
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_TIMEOUT;
}

static tmc2209_err_t port_rx(const tmc2209_bus_t *bus, uint8_t *buf, size_t len)
{
    int n = bus->port->rx(bus->port->ctx, buf, len, bus->timeout_ms);
    if (n < 0) {
        return TMC2209_ERR_IO;
    }
    trace(bus, false, buf, (size_t)n);
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_TIMEOUT;
}

/* On the single-wire bus everything transmitted lands back on rx. It is not
   merely discarded: a mismatch means something else drove the line during
   transmission, which is the cheapest bus-collision detector available. */
static tmc2209_err_t verify_echo(const tmc2209_bus_t *bus, const uint8_t *sent, size_t len)
{
    if (!bus->port->echoes) {
        return TMC2209_OK;
    }
    uint8_t echo[MAX_XFER];
    if (len > MAX_XFER) {
        return TMC2209_ERR_ARG;
    }
    tmc2209_err_t err = port_rx(bus, echo, len);
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
    err = port_rx(bus, reply, sizeof reply);
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

/* Retrying a read is always safe. Retrying a write is safe too, because every
   register written here is idempotent: writing the same value twice leaves the
   same state. The only cost is that IFCNT advances more than once, which is
   why confirm_writes() accepts a range rather than an exact delta. */
static tmc2209_err_t read_retrying(const tmc2209_bus_t *bus, uint8_t addr,
                                   tmc2209_reg_t reg, uint32_t *out)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= bus->retries; attempt++) {
        err = read_once(bus, addr, reg, out);
        if (err == TMC2209_OK) {
            return TMC2209_OK;
        }
        /* A reply for the wrong register means another driver answered.
           Retrying will not change that. */
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

/* Slots the firmware is the sole writer of, so the mask impose-like operations
   and tmc2209_trusted() work from. Built from the table rather than written
   out, so adding a register cannot leave the two disagreeing. */
static uint32_t owned_mask(void)
{
    uint32_t mask = 0;
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_OWNED) {
            mask |= (1u << slot);
        }
    }
    return mask;
}

static void mark_valid(tmc2209_t *dev, int slot, uint32_t value)
{
    dev->cache[slot] = value;
    dev->valid |= (1u << slot);
}

/* ── IFCNT verification ─────────────────────────────────────────────────── */

/* A write datagram gets no reply, so IFCNT is the only acknowledgement the
   chip offers. The caller states how many datagrams actually went on the wire;
   anything in [distinct, issued] means every distinct write landed, with the
   slack accounting for retried duplicates. */
static tmc2209_err_t confirm_writes(tmc2209_t *dev, unsigned distinct, unsigned issued)
{
    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    uint8_t  now   = tmc2209_ifcnt_decode(raw);
    unsigned delta = (uint8_t)(now - dev->ifcnt);   /* unsigned 8-bit subtraction wraps */
    dev->ifcnt = now;

    if (delta < distinct || delta > issued) {
        return TMC2209_ERR_NO_ACK;
    }
    return TMC2209_OK;
}

/* ── Batch write ────────────────────────────────────────────────────────── */

/* Every op is checked before any byte goes out, so a batch cannot be half
   sent and then rejected for naming a register it was never allowed to touch. */
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

/* True when a later op targets the same register, making this one dead. Keeps
   "last value wins" true without transmitting the values it supersedes. */
static bool superseded(const tmc2209_regval_t *ops, size_t n, size_t i)
{
    for (size_t j = i + 1; j < n; j++) {
        if (ops[j].reg == ops[i].reg) {
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
            dev->valid &= ~(1u << slot);
        }
    }
}

/* ── Public API ─────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_init(tmc2209_t *dev, const tmc2209_bus_t *bus, uint8_t addr)
{
    if (!dev || !bus || !bus->port || !bus->port->tx || !bus->port->rx) {
        return TMC2209_ERR_ARG;
    }
    if (addr > 3) {
        return TMC2209_ERR_ARG;
    }
    memset(dev, 0, sizeof *dev);
    dev->bus  = bus;
    dev->addr = addr;

    /* No slot is seeded. Datasheet reset values are not properties of the part
       for GCONF (OTP bits) or CHOPCONF (address straps), and a seeded value is
       one adopt() would go on to write. See design.md §7 item 7. */
    dev->valid = 0;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_adopt(tmc2209_t *dev,
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

    /* Every owned register must be named. There are no defaults to fill the
       gaps with, and a gap in GCONF is the difference between microstep
       resolution coming from CHOPCONF and coming from the address straps. */
    uint32_t covered = 0;
    for (size_t i = 0; i < n; i++) {
        covered |= (1u << tmc2209_reg_slot(config[i].reg));
    }
    if (covered != owned_mask()) {
        return TMC2209_ERR_ARG;
    }

    uint32_t raw = 0;

    /* Fail fast if the driver is not reachable: OK means framing, addressing
       and wiring work. */
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

    /* Bitwise write-1-to-clear, so raw is already the mask for the flags seen.
       GSTAT is volatile, so this goes around tmc2209_write() rather than
       through it: clearing latched flags is not configuration. */
    if (raw != 0) {
        unsigned issued = 0;
        err = write_retrying(dev->bus, dev->addr, TMC2209_GSTAT, raw, &issued);
        if (err == TMC2209_OK) {
            err = confirm_writes(dev, 1, issued);
        }
        if (err != TMC2209_OK) {
            return err;
        }
    }

    /* Constant registers hold per-part values, so they are read off this
       particular chip rather than assumed. A brownout will not change them,
       which is why tmc2209_distrust() leaves them alone. */
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
    /* A volatile register has no cached value by construction. Answering from
       the slot would return a plausible number that describes a moment which
       has passed, and would report a healthy driver sitting in overtemperature. */
    if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_VOLATILE) {
        return TMC2209_ERR_ACCESS;
    }
    if (!(dev->valid & (1u << slot))) {
        return TMC2209_ERR_STALE;
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

    /* The IFCNT baseline is part of knowing the device, so an untrusted cache
       has an untrustworthy baseline too. A passthrough write, for instance,
       advances the chip's counter without passing through here. Re-seed before
       verifying, or the batch that exists to recover would fail on its own
       stale baseline. */
    if (!tmc2209_trusted(dev)) {
        uint32_t raw = 0;
        err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
        if (err == TMC2209_OK) {
            dev->ifcnt = tmc2209_ifcnt_decode(raw);
        }
    }

    unsigned distinct = 0, issued = 0;
    size_t   stopped  = n;

    for (size_t i = 0; i < n && err == TMC2209_OK; i++) {
        int slot = tmc2209_reg_slot(ops[i].reg);

        /* A superseded op would be overwritten by a later one in the same
           batch, and an op matching a valid slot changes nothing. Dropping
           both recovers the "write only what changed" saving with no staging
           state to carry. */
        if (superseded(ops, n, i)) {
            continue;
        }
        if ((dev->valid & (1u << slot)) && dev->cache[slot] == ops[i].value) {
            continue;
        }

        err = write_retrying(dev->bus, dev->addr, ops[i].reg, ops[i].value, &issued);
        if (err != TMC2209_OK) {
            stopped = i;
            break;
        }
        distinct++;
    }

    /* One verification for the whole batch: n writes plus one read, rather
       than doubling the traffic with a read after every write. */
    if (err == TMC2209_OK && distinct > 0) {
        err = confirm_writes(dev, distinct, issued);
    }

    bus_unlock(dev->bus);

    if (failed_at) {
        *failed_at = stopped;
    }

    /* Nothing in a batch is confirmed until the IFCNT read, so an op that went
       out before the failure is no better known than one that never went out.
       The whole batch becomes unknown and the caller re-sends it. */
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
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_GSTAT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    tmc2209_gstat_t g = tmc2209_gstat_decode(raw);

    uint32_t found = 0;
    if (g.reset)   { found |= (uint32_t)TMC2209_LOST_CONFIG;  }
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
    /* Open load is reported but kept out of TMC2209_CONDITIONS_FAULT: it reads
       true at standstill and at low current, so treating it as a fault would
       trip continuously on a healthy motor. */
    if (s.ola || s.olb) {
        found |= (uint32_t)TMC2209_OPEN_LOAD;
    }

    /* The driver came up holding defaults, so nothing commanded is still in
       it. Recovery is the caller re-sending its configuration. */
    if ((found & (uint32_t)TMC2209_LOST_CONFIG) != 0) {
        tmc2209_distrust(dev);
    }

    *conditions = found;
    return TMC2209_OK;
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

    /* StallGuard reports nothing outside the TCOOLTHRS window, and a zero
       threshold closes the window entirely. Checking the speed bound as well
       needs the current step rate; see design.md §8. */
    uint32_t tcoolthrs = 0;
    bool armed = (tmc2209_read(dev, TMC2209_TCOOLTHRS, &tcoolthrs) == TMC2209_OK) &&
                 (tcoolthrs != 0);

    out->value = (uint16_t)(raw & 0x03FFu);
    out->valid = armed;
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

tmc2209_err_t tmc2209_poll_raw(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
{
    if (!dev || !dev->bus || !out) {
        return TMC2209_ERR_ARG;
    }
    uint8_t access = tmc2209_reg_access(reg);
    if (access == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!(access & TMC2209_ACC_R)) {
        return TMC2209_ERR_ACCESS;   /* write-only in silicon; the chip cannot answer */
    }

    bus_lock(dev->bus);
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, reg, out);
    bus_unlock(dev->bus);

    /* The cache is not updated. What the device answers says nothing about who
       owns the value, and adopting it for an owned register would let one
       stray read stand in for a write that never happened. */
    return err;
}

/* ── Verdicts ───────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_identify(tmc2209_t *dev)
{
    tmc2209_ioin_t pins;
    tmc2209_err_t err = tmc2209_poll_pins(dev, &pins);
    if (err != TMC2209_OK) {
        return err;
    }
    return (pins.version == TMC2209_IOIN_VERSION) ? TMC2209_OK : TMC2209_ERR_PART;
}

tmc2209_err_t tmc2209_verify_config(tmc2209_t *dev, uint32_t *mismatched)
{
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }

    uint32_t bad = 0;
    tmc2209_err_t err = TMC2209_OK;

    bus_lock(dev->bus);
    for (int slot = 0; slot < TMC2209_REG_COUNT && err == TMC2209_OK; slot++) {
        /* Only the owned registers the silicon will answer for. The other
           eight are write-only, so there is nothing to compare against. */
        if (tmc2209_reg_class_at(slot) != TMC2209_CLASS_OWNED ||
            !(tmc2209_reg_access_at(slot) & TMC2209_ACC_R)    ||
            !(dev->valid & (1u << slot))) {
            continue;
        }
        uint32_t raw = 0;
        err = read_retrying(dev->bus, dev->addr, tmc2209_reg_at(slot), &raw);
        if (err == TMC2209_OK && raw != dev->cache[slot]) {
            bad |= (1u << slot);
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

bool tmc2209_trusted(const tmc2209_t *dev)
{
    if (!dev) {
        return false;
    }
    uint32_t owned = owned_mask();
    return (dev->valid & owned) == owned;
}

void tmc2209_distrust(tmc2209_t *dev)
{
    if (dev) {
        dev->valid &= ~owned_mask();
    }
}

/* ── Passthrough ────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_bus_xfer(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len)
{
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
    if (err == TMC2209_OK && rx_len > 0) {
        err = port_rx(bus, rx, rx_len);
    }

    bus_unlock(bus);
    return err;
}
