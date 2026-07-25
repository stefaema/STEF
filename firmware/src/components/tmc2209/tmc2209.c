#include "tmc2209.h"

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

/* On the single-wire bus everything we transmit lands back on rx. We do not
   merely discard it: a mismatch means something else drove the line while we
   were talking, which is the cheapest bus-collision detector available. */
static tmc2209_err_t consume_echo(const tmc2209_bus_t *bus, const uint8_t *sent, size_t len)
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

static tmc2209_err_t try_read(const tmc2209_bus_t *bus, uint8_t addr,
                              tmc2209_reg_t reg, uint32_t *out)
{
    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, addr, (uint8_t)reg);

    bus_purge(bus);

    tmc2209_err_t err = port_tx(bus, req, sizeof req);
    if (err != TMC2209_OK) {
        return err;
    }
    err = consume_echo(bus, req, sizeof req);
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

static tmc2209_err_t try_write(const tmc2209_bus_t *bus, uint8_t addr,
                               tmc2209_reg_t reg, uint32_t value)
{
    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, addr, (uint8_t)reg, value);

    bus_purge(bus);

    tmc2209_err_t err = port_tx(bus, dg, sizeof dg);
    if (err != TMC2209_OK) {
        return err;
    }
    return consume_echo(bus, dg, sizeof dg);
}

/* Retrying a read is always safe. Retrying a write is safe too, because every
   register we write is idempotent: writing the same value twice leaves the
   same state. The only cost is that IFCNT advances more than once, which is
   why the verification below accepts a range rather than an exact delta. */
static tmc2209_err_t read_retrying(const tmc2209_bus_t *bus, uint8_t addr,
                                   tmc2209_reg_t reg, uint32_t *out)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= bus->retries; attempt++) {
        err = try_read(bus, addr, reg, out);
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

/* ── IFCNT verification ─────────────────────────────────────────────────── */

/* A write datagram gets no reply, so IFCNT is the only acknowledgement the
   chip offers. Caller states how many datagrams it actually put on the wire;
   anything in [distinct, issued] means every distinct write landed, with the
   slack accounting for retried duplicates. */
static tmc2209_err_t confirm_writes(tmc2209_t *dev, unsigned distinct, unsigned issued)
{
    uint32_t raw = 0;
    tmc2209_err_t err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    uint8_t  now   = (uint8_t)(raw & 0xFFu);
    unsigned delta = (unsigned)((uint8_t)(now - dev->ifcnt));   /* wraps at 255 */
    dev->ifcnt = now;

    if (delta < distinct || delta > issued) {
        return TMC2209_ERR_NO_ACK;
    }
    return TMC2209_OK;
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
    dev->bus     = bus;
    dev->addr    = addr;
    dev->trusted = false;   /* nothing has been imposed on the device yet */

    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        dev->shadow[slot] = tmc2209_reg_reset_at(slot);
    }
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_begin(tmc2209_t *dev)
{
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }

    /* IOIN.version is a free comms self-test: it proves framing, CRC and
       wiring all work before we depend on any of them. */
    uint32_t raw = 0;
    tmc2209_err_t err = tmc2209_read(dev, TMC2209_IOIN, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    if (tmc2209_ioin_decode(raw).version != TMC2209_IOIN_VERSION) {
        return TMC2209_ERR_VERSION;
    }

    /* Seed the write counter before issuing any write, or the first
       verification compares against a number we never observed. */
    err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    dev->ifcnt = (uint8_t)(raw & 0xFFu);

    /* Clear whatever is latched, including the power-on reset flag, so the
       next GSTAT read reports only what happened since we took charge. */
    err = tmc2209_read(dev, TMC2209_GSTAT, &raw);
    if (err != TMC2209_OK) {
        return err;
    }
    if (raw != 0) {
        err = tmc2209_write(dev, TMC2209_GSTAT, raw);
        if (err != TMC2209_OK) {
            return err;
        }
    }

    return tmc2209_reflush(dev);
}

tmc2209_err_t tmc2209_read(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
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

    if (err != TMC2209_OK) {
        return err;
    }

    /* For registers the chip reads back, a fresh read is better evidence than
       the shadow, so adopt it and drop any pending stage. */
    if ((access & TMC2209_ACC_R) && (access & TMC2209_ACC_W)) {
        int slot = tmc2209_reg_slot(reg);
        dev->shadow[slot] = *out;
        dev->dirty &= ~(1u << slot);
    }

    /* GSTAT.reset means the driver browned out and lost its configuration.
       Everything we believe about it is now fiction. */
    if (reg == TMC2209_GSTAT && tmc2209_gstat_decode(*out).reset) {
        dev->trusted = false;
    }
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_write(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value)
{
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }
    uint8_t access = tmc2209_reg_access(reg);
    if (access == 0) {
        return TMC2209_ERR_ARG;
    }
    if (!(access & TMC2209_ACC_W)) {
        return TMC2209_ERR_ACCESS;
    }

    bus_lock(dev->bus);

    unsigned issued = 0;
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= dev->bus->retries; attempt++) {
        issued++;
        err = try_write(dev->bus, dev->addr, reg, value);
        if (err == TMC2209_OK) {
            break;
        }
    }
    if (err == TMC2209_OK) {
        err = confirm_writes(dev, 1, issued);
    }

    bus_unlock(dev->bus);

    if (err != TMC2209_OK) {
        /* We do not know whether it landed, so we no longer know the device. */
        dev->trusted = false;
        return err;
    }

    int slot = tmc2209_reg_slot(reg);
    dev->shadow[slot] = value;
    dev->dirty &= ~(1u << slot);
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_cached(const tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out)
{
    if (!dev || !out) {
        return TMC2209_ERR_ARG;
    }
    int slot = tmc2209_reg_slot(reg);
    if (slot < 0) {
        return TMC2209_ERR_ARG;
    }
    if (!dev->trusted) {
        return TMC2209_ERR_STALE;   /* refuse rather than lie quietly */
    }
    *out = dev->shadow[slot];
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_stage(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    int slot = tmc2209_reg_slot(reg);
    if (slot < 0) {
        return TMC2209_ERR_ARG;
    }
    if (!(tmc2209_reg_access_at(slot) & TMC2209_ACC_W)) {
        return TMC2209_ERR_ACCESS;
    }
    dev->shadow[slot] = value;
    dev->dirty |= (1u << slot);
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_flush(tmc2209_t *dev)
{
    if (!dev || !dev->bus) {
        return TMC2209_ERR_ARG;
    }
    if (dev->dirty == 0) {
        return TMC2209_OK;
    }

    bus_lock(dev->bus);

    unsigned distinct = 0, issued = 0;
    uint32_t written  = 0;
    tmc2209_err_t err = TMC2209_OK;

    /* The IFCNT baseline is part of knowing the device, so an untrusted shadow
       has an untrustworthy baseline too. A passthrough write, for instance,
       advances the chip's counter without passing through here. Re-seed before
       verifying, or reflush would refuse to perform the recovery it exists for. */
    if (!dev->trusted) {
        uint32_t raw = 0;
        err = read_retrying(dev->bus, dev->addr, TMC2209_IFCNT, &raw);
        if (err == TMC2209_OK) {
            dev->ifcnt = (uint8_t)(raw & 0xFFu);
        }
    }

    for (int slot = 0; slot < TMC2209_REG_COUNT && err == TMC2209_OK; slot++) {
        if (!(dev->dirty & (1u << slot))) {
            continue;
        }
        tmc2209_reg_t reg = tmc2209_reg_at(slot);

        tmc2209_err_t werr = TMC2209_ERR_IO;
        for (unsigned attempt = 0; attempt <= dev->bus->retries; attempt++) {
            issued++;
            werr = try_write(dev->bus, dev->addr, reg, dev->shadow[slot]);
            if (werr == TMC2209_OK) {
                break;
            }
        }
        if (werr != TMC2209_OK) {
            err = werr;
            break;
        }
        distinct++;
        written |= (1u << slot);
    }

    /* One verification for the whole batch: N writes plus one read, rather
       than doubling the traffic with a read after every write. */
    if (err == TMC2209_OK) {
        err = confirm_writes(dev, distinct, issued);
    }

    bus_unlock(dev->bus);

    if (err != TMC2209_OK) {
        dev->trusted = false;
        return err;
    }

    dev->dirty &= ~written;
    if (dev->dirty == 0) {
        dev->trusted = true;
    }
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_reflush(tmc2209_t *dev)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    /* Eight registers are write-only, so the device cannot be interrogated
       back into agreement. The only way to a trusted shadow is to impose it. */
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_access_at(slot) & TMC2209_ACC_CONFIG) {
            dev->dirty |= (1u << slot);
        }
    }
    return tmc2209_flush(dev);
}

bool tmc2209_trusted(const tmc2209_t *dev)
{
    return dev && dev->trusted;
}

void tmc2209_invalidate(tmc2209_t *dev)
{
    if (dev) {
        dev->trusted = false;
    }
}

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
        err = consume_echo(bus, tx, tx_len);
    }
    if (err == TMC2209_OK && rx_len > 0) {
        err = port_rx(bus, rx, rx_len);
    }

    bus_unlock(bus);
    return err;
}
