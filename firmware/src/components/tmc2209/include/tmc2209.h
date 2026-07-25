/**
 * @file tmc2209.h
 * @brief One driver on a shared single-wire UART bus.
 *
 * Not thread-safe. One device has one owner; on target that owner is the
 * control task. The port's lock/unlock hooks exist for the PC-side harness.
 */

#ifndef TMC2209_H
#define TMC2209_H

#include "tmc2209_frame.h"
#include "tmc2209_port.h"
#include "tmc2209_reg.h"

typedef struct {
    const tmc2209_port_t *port;
    uint32_t timeout_ms;   /**< per port call */
    uint8_t  retries;      /**< additional attempts after a CRC or timeout failure */
} tmc2209_bus_t;

typedef struct {
    const tmc2209_bus_t *bus;
    uint8_t  addr;                        /**< 0..3, set by the MS1/MS2 straps */
    uint8_t  ifcnt;                       /**< last observed write counter */
    bool     trusted;                     /**< device state is derivable from shadow */
    uint32_t shadow[TMC2209_REG_COUNT];   /**< what we commanded, not what we measured */
    uint32_t dirty;                       /**< staged but not yet written; one bit per slot */
} tmc2209_t;

/**
 * @brief Construction only. Seeds shadow with reset values, starts untrusted.
 *
 * @param dev   device to initialise; overwritten entirely
 * @param bus   borrowed, must outlive @p dev
 * @param addr  0..3, matching the MS1/MS2 straps
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null argument, port without tx/rx, or addr > 3
 */
tmc2209_err_t tmc2209_init(tmc2209_t *dev, const tmc2209_bus_t *bus, uint8_t addr);

/**
 * @brief Bring-up. Seeds IFCNT, clears GSTAT, then imposes the shadow on the
 *        device. Shadow config is now trusted on success.
 *
 * Clearing GSTAT is what gives the flag its meaning afterwards: latched, it
 * cannot distinguish a reset that just happened from one at power-on. So the
 * pre-clear value is handed back through @p at_bringup, the only chance anyone
 * gets to see what the driver went through before we owned it.
 *
 * Note this says nothing about why the *controller* restarted; that is
 * esp_reset_reason()'s answer, and the two together are what separate a supply
 * sag from a firmware panic.
 *
 * @param dev         initialised device
 * @param at_bringup  GSTAT as found, before it is cleared. NULL to discard
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null device or missing bus
 * @retval TMC2209_ERR_NO_ACK   IFCNT did not account for the writes issued
 * @return any transport error from the underlying read and write
 */
tmc2209_err_t tmc2209_begin(tmc2209_t *dev, tmc2209_gstat_t *at_bringup);

/* ── Device access ──────────────────────────────────────────────────────── */

/**
 * @brief Hits the wire. Refuses write-only registers.
 *
 * Updates the shadow for registers the chip will actually read back. Reading
 * GSTAT with the reset flag set drops trust: the driver lost its configuration.
 *
 * @param dev  device
 * @param reg  register to read
 * @param out  raw 32-bit value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null argument, or a register not in the table
 * @retval TMC2209_ERR_ACCESS   write-only in silicon; the chip cannot answer
 * @retval TMC2209_ERR_TIMEOUT  nothing answered in time
 * @retval TMC2209_ERR_IO       the port failed for its own reasons
 * @retval TMC2209_ERR_ECHO     our own bytes came back altered: bus collision
 * @retval TMC2209_ERR_SYNC     reply sync byte or master address wrong
 * @retval TMC2209_ERR_CRC      reply CRC mismatch, retries exhausted
 * @retval TMC2209_ERR_REG      another driver answered; not retried
 */
tmc2209_err_t tmc2209_read(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/**
 * @brief Hits the wire and verifies via IFCNT.
 *
 * Updates the shadow, so a raw RPC write keeps the shadow true rather than
 * desyncing it. A write whose acknowledgement could not be confirmed drops
 * trust, because we do not know whether it landed.
 *
 * @param dev    device
 * @param reg    register to write
 * @param value  raw 32-bit value
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null device, or a register not in the table
 * @retval TMC2209_ERR_ACCESS   read-only by silicon or by our policy
 * @retval TMC2209_ERR_NO_ACK   IFCNT did not advance: the write never landed
 * @return any transport error from the datagram or its IFCNT confirmation
 */
tmc2209_err_t tmc2209_write(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value);

/* ── Shadow access ──────────────────────────────────────────────────────── */

/**
 * @brief Reads a register from the shadow.
 *
 * What we commanded, not what we measured. Returns TMC2209_ERR_STALE rather
 * than a stale value: a shadow that lies quietly is worse than no shadow.
 *
 * @param dev  device
 * @param reg  register to look up
 * @param out  shadow value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG    null argument, or a register not in the table
 * @retval TMC2209_ERR_STALE  shadow is untrusted; reflush before believing it
 */
tmc2209_err_t tmc2209_shadow(const tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/**
 * @brief Records an intended value and marks it for the next flush. No I/O.
 *
 * @param dev    device
 * @param reg    register to stage
 * @param value  raw 32-bit value
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null device, or a register not in the table
 * @retval TMC2209_ERR_ACCESS  read-only by silicon or by our policy
 */
tmc2209_err_t tmc2209_stage(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t value);

/**
 * @brief Writes only what changed, then confirms IFCNT advanced by the number
 *        of writes issued.
 *
 * One verification for the batch rather than one per register. A batch that
 * cannot be confirmed drops trust, leaving the dirty bits set.
 *
 * @param dev  device
 *
 * @retval TMC2209_OK          nothing was dirty, or every staged write landed
 * @retval TMC2209_ERR_ARG     null device or missing bus
 * @retval TMC2209_ERR_NO_ACK  IFCNT did not account for the writes issued
 * @return any transport error from the datagrams or their confirmation
 */
tmc2209_err_t tmc2209_flush(tmc2209_t *dev);

/**
 * @brief Marks every shadow config register dirty and flushes them into the
 *        device. This is the only way back to a trusted shadow.
 *
 * @param dev  device
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null device
 * @return anything tmc2209_flush() can return
 */
tmc2209_err_t tmc2209_reflush(tmc2209_t *dev);

/** @brief True when the shadow may be believed. False for a NULL device. */
bool tmc2209_trusted(const tmc2209_t *dev);

/** @brief Declares the shadow no longer derivable from what we commanded. */
void tmc2209_invalidate(tmc2209_t *dev);

/* ── Passthrough ────────────────────────────────────────────────────────── */

/**
 * @brief Sends raw bytes and optionally waits for a fixed-length reply.
 *
 * Bytes in, bytes out, no interpretation. Keeps the lock and the echo
 * discipline, skips framing and the shadow entirely. This is what the RPC
 * passthrough mode and the HIL tier drive.
 *
 * Callers that use this to write must call tmc2209_invalidate(): a datagram we
 * did not build is one we cannot account for.
 *
 * @param bus     bus to drive; no device state is consulted or updated
 * @param tx      bytes to send, 1..32
 * @param tx_len  length of @p tx
 * @param rx      reply buffer, or NULL when @p rx_len is 0
 * @param rx_len  exact number of bytes to wait for; 0 to send only
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null bus or tx, empty or oversized tx, rx_len
 *                              without rx
 * @retval TMC2209_ERR_TIMEOUT  fewer than @p rx_len bytes arrived in time
 * @retval TMC2209_ERR_IO       the port failed for its own reasons
 * @retval TMC2209_ERR_ECHO     our own bytes came back altered: bus collision
 */
tmc2209_err_t tmc2209_bus_xfer(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len);

#endif /* TMC2209_H */
