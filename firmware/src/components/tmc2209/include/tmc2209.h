/**
 * @file tmc2209.h
 * @brief One driver on a shared single-wire UART bus.
 *
 * Three families of call, distinguished by what they do rather than by which
 * register they touch. See design.md §3.
 *
 *   - Values are @b read and @b written. Reads come from the cache and never
 *     touch the bus; writes go out as a batch and are verified once.
 *   - Conditions are @b polled. Every poll_ call performs a transaction and
 *     returns meaning rather than register contents.
 *   - Verdicts come from tmc2209_identify() and tmc2209_verify_config(), which
 *     return pass or fail rather than a number.
 *
 * The library reports conditions and never decides responses. What
 * GSTAT.reset means is a fact about the chip; whether it should fault the reel
 * is control policy and lives above.
 *
 * Not thread-safe: one device, one owner.
 */

#ifndef TMC2209_H
#define TMC2209_H

#include "tmc2209_port.h"
#include "tmc2209_reg.h"

/** Element count of a configuration array literal. */
#define TMC2209_NELEM(a) (sizeof(a) / sizeof((a)[0]))

typedef struct {
    const tmc2209_port_t *port;
    uint32_t timeout_ms;   /**< per port call */
    uint8_t  retries;      /**< additional attempts after a CRC or timeout failure */
} tmc2209_bus_t;

/** One register and the value intended for it. The unit of tmc2209_write(). */
typedef struct {
    tmc2209_reg_t reg;
    uint32_t      value;
} tmc2209_regval_t;

typedef struct {
    const tmc2209_bus_t *bus;
    uint8_t  addr;                       /**< 0..3, set by the MS1/MS2 straps */
    uint8_t  ifcnt;                      /**< last observed write counter */
    uint32_t cache[TMC2209_REG_COUNT];   /**< last known value per slot */
    uint32_t valid;                      /**< one bit per slot: device holds cache[slot] */
} tmc2209_t;

/**
 * @brief Construction only. No I/O, no defaults.
 *
 * Every slot starts invalid. There are no datasheet reset values to fall back
 * on, so nothing can be read or written until tmc2209_adopt() supplies a
 * configuration.
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
 * @brief Claims a reachable driver and writes @p config to it.
 *
 * Probes the driver, seeds the IFCNT baseline, clears GSTAT, reads the
 * CONSTANT registers off this particular part, and writes the configuration.
 *
 * @p config must cover all @ref TMC2209_OWNED_COUNT owned registers. A partial
 * configuration is rejected rather than completed from defaults: the datasheet
 * reset values for GCONF and CHOPCONF are not properties of the part number,
 * and writing them would clear mstep_reg_select and hand microstep resolution
 * back to the address straps.
 *
 * GSTAT as found is handed back through @p at_bringup before it is cleared,
 * which is the only chance to see what the driver went through before this
 * firmware owned it. It says nothing about why the *controller* restarted;
 * that is esp_reset_reason()'s answer.
 *
 * @param dev         initialised device
 * @param config      one entry per owned register, in any order
 * @param n           length of @p config
 * @param at_bringup  GSTAT as found, before it is cleared. NULL to discard
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null argument, or @p config does not cover
 *                              every owned register
 * @retval TMC2209_ERR_ACCESS   @p config names a register that is not owned
 * @retval TMC2209_ERR_NO_ACK   IFCNT did not account for the writes issued
 * @return any transport error from the underlying reads and writes
 */
tmc2209_err_t tmc2209_adopt(tmc2209_t *dev,
                            const tmc2209_regval_t *config, size_t n,
                            tmc2209_gstat_t *at_bringup);

/* ── Values ─────────────────────────────────────────────────────────────── */

/**
 * @brief Reads a register from the cache. Never touches the bus.
 *
 * Serves owned and constant registers. Volatile registers are refused: the
 * silicon changes them, so a remembered copy describes a moment that has
 * passed. tmc2209_poll_health() and friends are the way to obtain those.
 *
 * @param dev  device
 * @param reg  register to look up
 * @param out  cached value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument, or a register not in the table
 * @retval TMC2209_ERR_ACCESS  volatile register; there is no cached value
 * @retval TMC2209_ERR_STALE   slot is invalid; nothing here can be believed
 */
tmc2209_err_t tmc2209_read(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/**
 * @brief Writes a batch of owned registers and verifies that it landed.
 *
 * The array is the unit of work: @p n datagrams followed by one IFCNT check,
 * so a ten-register configuration costs eleven transactions rather than
 * twenty. Every op is validated before any byte goes out.
 *
 * Behaviour worth knowing at a call site:
 *
 *   - **Ordering.** Applied in order. A register named twice takes its last
 *     value, and the superseded ops are dropped rather than transmitted.
 *   - **Skipping.** An op whose value already matches a valid slot is dropped.
 *     A batch may therefore put zero datagrams on the wire.
 *   - **Failure.** Any failure invalidates *every* slot in the batch, including
 *     ops transmitted before the failure. Nothing in a batch is confirmed until
 *     the IFCNT read at the end, so an early abort leaves even the transmitted
 *     ops unverified. Recovery is to re-send the batch.
 *
 * @param dev        device
 * @param ops        registers and values, 1..n
 * @param n          length of @p ops
 * @param failed_at  diagnostic only: which op the library was on when it gave
 *                   up, or @p n when no single op is at fault. NULL to discard.
 *                   This is not where the state boundary is; see Failure above
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null argument, empty batch, or a register not
 *                              in the table
 * @retval TMC2209_ERR_ACCESS   a register that is not owned
 * @retval TMC2209_ERR_NO_ACK   IFCNT did not account for the writes issued
 * @return any transport error from the datagrams or their confirmation
 */
tmc2209_err_t tmc2209_write(tmc2209_t *dev,
                            const tmc2209_regval_t *ops, size_t n,
                            size_t *failed_at);

/* ── Conditions ─────────────────────────────────────────────────────────── */

/**
 * @brief Reads GSTAT and DRV_STATUS, and reports what is wrong.
 *
 * One condition set from two registers, so the caller never learns which
 * register a given fault came from.
 *
 * TMC2209_LOST_CONFIG invalidates every owned slot: the driver browned out and
 * no longer holds the configuration. Recovery is not this library's job, since
 * eight registers cannot be read back; the PC re-sends the configuration. That
 * is deliberate, because a driver that reset mid-reel also lost VACTUAL and any
 * position estimate built on it, which is a mechanical event rather than a
 * cache miss.
 *
 * @param dev         device
 * @param conditions  bitmask of @ref tmc2209_condition_t, 0 when healthy
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null argument
 * @return any transport error from either read
 */
tmc2209_err_t tmc2209_poll_health(tmc2209_t *dev, uint32_t *conditions);

/**
 * @brief Reads the StallGuard load estimate, with whether it can be believed.
 *
 * SG_RESULT is only meaningful inside the TCOOLTHRS speed window, so a raw
 * number on its own invites a control loop to act on noise. This checks what
 * it can: TCOOLTHRS of zero means StallGuard is disabled outright.
 *
 * The speed-dependent half of the check needs the current step rate and waits
 * on stepgen. See design.md §8.
 *
 * @param dev  device
 * @param out  load estimate and its validity
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null argument
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_poll_load(tmc2209_t *dev, tmc2209_load_t *out);

/**
 * @brief Reads the live input pin states.
 *
 * Returns the decoded struct rather than a condition, because pin-level detail
 * is exactly what a bring-up caller is asking for.
 *
 * @param dev  device
 * @param out  decoded pin state
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null argument
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_poll_pins(tmc2209_t *dev, tmc2209_ioin_t *out);

/**
 * @brief Reads any readable register off the device, uninterpreted.
 *
 * The path for MSCNT, MSCURACT, PWM_SCALE and PWM_AUTO, which carry no
 * condition worth naming, and for a diagnostic that dumps the whole device.
 * Does not update the cache: a device read is not evidence about who owns the
 * value.
 *
 * @param dev  device
 * @param reg  register to read
 * @param out  raw value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument, or a register not in the table
 * @retval TMC2209_ERR_ACCESS  write-only in silicon; the chip cannot answer
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_poll_raw(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/* ── Verdicts ───────────────────────────────────────────────────────────── */

/**
 * @brief Confirms that the part at this address is the expected silicon.
 *
 * Checks the IOIN version byte, which is fixed for the part. A TMC2208 answers
 * 0x20 and is rejected.
 *
 * @param dev  device
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG   null argument
 * @retval TMC2209_ERR_PART  something answered, but it is not this part
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_identify(tmc2209_t *dev);

/**
 * @brief Checks the cache against the silicon for the registers that read back.
 *
 * Only GCONF and CHOPCONF can be checked, since the other eight owned
 * registers are write-only. Exists so the HIL tier can assert that the cache
 * is telling the truth, which is the test that validates the whole caching
 * scheme. Nothing in the control path calls it.
 *
 * @param dev         device
 * @param mismatched  bitmask of slots that disagree, 0 when all agree.
 *                    NULL to discard
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG       null device
 * @retval TMC2209_ERR_MISMATCH  the device disagrees with the cache
 * @return any transport error from the reads
 */
tmc2209_err_t tmc2209_verify_config(tmc2209_t *dev, uint32_t *mismatched);

/* ── Runtime writes ─────────────────────────────────────────────────────── */

/**
 * @brief Sets the internal velocity generator. Immediate and verified.
 *
 * A non-zero value takes the driver off its STEP pin, silently and with no
 * fault raised, so it must be returned to zero before coordinated motion. The
 * actuator layer owns that precondition; this is the verb it uses.
 *
 * VACTUAL is write-only in silicon, so the value can only ever be checked
 * against the cache. That is authoritative while the slot is valid, and
 * TMC2209_LOST_CONFIG is what ends the guarantee.
 *
 * @param dev  device
 * @param v    signed 24-bit velocity; 0 returns control to the STEP pin
 *
 * @return as tmc2209_write() for a one-register batch
 */
tmc2209_err_t tmc2209_set_velocity(tmc2209_t *dev, int32_t v);

/**
 * @brief Sets run and hold current. Immediate and verified.
 *
 * A runtime write rather than configuration: reel diameter changes as film
 * winds, so torque has to track it.
 *
 * @param dev  device
 * @param c    run current, hold current, and the ramp between them
 *
 * @return as tmc2209_write() for a one-register batch
 */
tmc2209_err_t tmc2209_set_current(tmc2209_t *dev, const tmc2209_ihold_irun_t *c);

/* ── Cache validity ─────────────────────────────────────────────────────── */

/** @brief True when every owned slot is valid. False for a NULL device. */
bool tmc2209_trusted(const tmc2209_t *dev);

/**
 * @brief Invalidates every owned slot.
 *
 * Constant slots survive, since a brownout does not change the factory trim.
 * Callers that write through tmc2209_bus_xfer() must call this: a datagram the
 * library did not build is one it cannot account for.
 */
void tmc2209_distrust(tmc2209_t *dev);

/* ── Passthrough ────────────────────────────────────────────────────────── */

/**
 * @brief Sends raw bytes and optionally waits for a fixed-length reply.
 *
 * Bytes in, bytes out, no interpretation. Keeps the lock and the echo
 * discipline, skips framing and the cache entirely. This is what the RPC
 * passthrough mode and the HIL tier drive.
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
