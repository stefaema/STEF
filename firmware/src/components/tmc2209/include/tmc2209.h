/*
 * tmc2209.h — one driver on a shared single-wire UART bus.
 *
 * Not thread-safe. One device has one owner; on target that owner is the
 * control task. The port's lock/unlock hooks exist for the PC-side harness.
 *
 * This library touches no GPIO. STEP, DIR, EN and DIAG belong to the actuator
 * layer above. Keeping them out is what lets this whole component compile and
 * test natively with no ESP-IDF at all.
 */

#ifndef TMC2209_H
#define TMC2209_H

#include "tmc2209_frame.h"
#include "tmc2209_port.h"
#include "tmc2209_reg.h"

typedef struct {
    const tmc2209_port_t *port;
    uint32_t timeout_ms;   /* per port call */
    uint8_t  retries;      /* additional attempts after a CRC or timeout failure */
} tmc2209_bus_t;

typedef struct {
    const tmc2209_bus_t *bus;
    uint8_t  addr;                            /* 0..3, set by the MS1/MS2 straps */
    uint8_t  ifcnt;                           /* last observed write counter */
    bool     trusted;                         /* device state is derivable from shadow */
    uint32_t shadow[TMC2209_REG_COUNT];       /* what we commanded, not what we measured */
    uint32_t dirty;                           /* staged but not yet written; one bit per slot */
} tmc2209_t;

/* Construction only. No I/O, so a test can build one on the stack.
   Seeds the shadow with the chip's reset values and starts untrusted. */
tmc2209_err_t tmc2209_init(tmc2209_t *dev, const tmc2209_bus_t *bus, uint8_t addr);

/* Bring-up. Confirms IOIN.version, seeds IFCNT, clears GSTAT, then imposes the
   shadow on the device. Trusted on success. */
tmc2209_err_t tmc2209_begin(tmc2209_t *dev);

/* ── Device access ──────────────────────────────────────────────────────── */

/* Hits the wire. Refuses write-only registers. Updates the shadow for
   registers the chip will actually read back. */
tmc2209_err_t tmc2209_read(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/* Hits the wire and verifies via IFCNT. Updates the shadow, so a raw RPC write
   keeps the shadow true rather than desyncing it. */
tmc2209_err_t tmc2209_write(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value);

/* ── Shadow access ──────────────────────────────────────────────────────── */

/* What we commanded. Returns TMC2209_ERR_STALE rather than a stale value:
   a shadow that lies quietly is worse than no shadow. */
tmc2209_err_t tmc2209_cached(const tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/* Shadow plus dirty bit. No I/O. */
tmc2209_err_t tmc2209_stage(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value);

/* Writes only what changed, then confirms IFCNT advanced by the number of
   writes issued. One verification for the batch rather than one per register. */
tmc2209_err_t tmc2209_flush(tmc2209_t *dev);

/* Marks every config register dirty and flushes. This is the only way back to
   a trusted shadow: eight registers are write-only, so the device cannot be
   interrogated, only overwritten. */
tmc2209_err_t tmc2209_reflush(tmc2209_t *dev);

bool tmc2209_trusted(const tmc2209_t *dev);
void tmc2209_invalidate(tmc2209_t *dev);

/* ── Passthrough ────────────────────────────────────────────────────────── */

/* Bytes in, bytes out, no interpretation. Keeps the lock and the echo
   discipline, skips framing and the shadow entirely. This is what the RPC
   passthrough mode and the HIL tier drive.
   Callers that use this to write must call tmc2209_invalidate(): a datagram
   we did not build is one we cannot account for. */
tmc2209_err_t tmc2209_bus_xfer(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len);

#endif /* TMC2209_H */
