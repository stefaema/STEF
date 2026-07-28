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
 *   - Verdicts come from tmc2209_verify_config(), which returns pass or fail
 *     rather than a number.
 *
 * Alongside those, the driver's four control lines. They are levels rather
 * than registers, so they do not fit the three families above, but what each
 * one means is the datasheet's answer and not the board's. See
 * tmc2209_lines.h.
 *
 * The library reports conditions and never decides responses. What
 * GSTAT.reset means is a fact about the driver; whether it should fault the reel
 * is control policy and lives above.
 *
 * Not thread-safe: one device, one owner.
 */

#ifndef TMC2209_H
#define TMC2209_H

#include "tmc2209_err.h"
#include "tmc2209_lines.h"
#include "tmc2209_port.h"
#include "tmc2209_reg.h"

/** Element count of a configuration array literal. */
#define TMC2209_NELEM(a) (sizeof(a) / sizeof((a)[0]))

/** @brief The shared wire. One bus, up to four drivers addressed on it. */
typedef struct {
    const tmc2209_port_t *port;
    uint32_t timeout_ms;   /**< per port call */
    uint8_t  retries;      /**< additional attempts after a CRC or timeout failure */
} tmc2209_bus_t;

/** @brief One register and the value intended for it. The unit of tmc2209_write(). */
typedef struct {
    tmc2209_reg_t reg;
    uint32_t      value;
} tmc2209_regval_t;

/** @brief One driver, and everything known about what it currently holds. */
typedef struct {
    const tmc2209_bus_t *bus;            /**< UART comm channel */
    const tmc2209_lines_t *lines;        /**< control lines, NULL until attached */
    uint8_t  addr;                       /**< 0..3, set by the MS1/MS2 straps */
    uint8_t  ifcnt;                      /**< last observed write counter */
    uint32_t cache[TMC2209_REG_COUNT];   /**< last known value per slot */
    uint32_t valid;                      /**< one bit per slot: device holds cache[slot] */
} tmc2209_t;

/**
 * @brief Construction only.
 *
 * Every slot starts invalid. Nothing can be read or written until `tmc2209_adopt()` supplies a
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
 * configuration is rejected.
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
 * @brief Reads a register from the cache.
 *
 * Serves owned and constant registers. Volatile registers are refused: the
 * driver changes them, so a remembered copy describes a moment that has
 * passed. tmc2209_poll_health() and friends are the way to obtain those.
 *
 * @param dev  device
 * @param reg  register to look up
 * @param out  cached value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument, or a register not in the table
 * @retval TMC2209_ERR_ACCESS  volatile register; there is no cached value
 * @retval TMC2209_ERR_INVALID_SLOT   slot is invalid; nothing here can be believed
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
 * One condition set from two registers.
 *
 * TMC2209_DRIVER_RESET invalidates every owned slot as sync was lost with the driver.
 * Configuration backup should be handled outside the library.
 *
 * Purely observational: the latched half of @ref tmc2209_condition_t therefore stays
 * asserted across polls until tmc2209_clear_faults() acknowledges it.
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
 * @brief Acknowledges latched conditions so they stop being reported.
 *
 * GSTAT flags are latched in the driver: once set they stay set until a 1 is
 * written back.
 *
 * Pass back the conditions received from `tmc2209_poll_health()`. Only the bits
 * in @ref TMC2209_CONDITIONS_LATCHED are acted on; live conditions are ignored,
 * so handing the whole set straight back is the intended use. Acknowledging
 * only what was actually seen is also what makes this safe against a fault that
 * latches between the poll and the acknowledgement: it survives to be reported.
 *
 * This validates nothing. Clearing `TMC2209_DRIVER_RESET` says the reset was
 * noticed, not that the configuration was rewritten; only a successful
 * `tmc2209_write()` covering the owned registers does that (see `tmc2209_adopt()`).
 *
 * @param dev         device
 * @param conditions  conditions to acknowledge; 0 does nothing and touches no bus
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument
 * @retval TMC2209_ERR_NO_ACK  IFCNT did not account for the write
 * @return any transport error from the write or its confirmation
 */
tmc2209_err_t tmc2209_clear_faults(tmc2209_t *dev, uint32_t conditions);

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
 * is exactly what a bring-up caller is asking for. IOIN also carries the
 * driver revision; tmc2209_poll_version() is the way to ask for that.
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
 * @brief Reads the revision of the driver answering at this address.
 *
 * The IOIN version field is a compatibility generation, not a model number:
 * @ref TMC2209_IOIN_VERSION is the first revision of the TMC2209, and a
 * TMC2208 answering 0x20 is a side effect rather than the field's purpose.
 * A later revision would report a different number and still be a TMC2209.
 *
 * Reported rather than judged. Which revisions an installation accepts is a
 * policy question, so the caller compares against @ref TMC2209_IOIN_VERSION,
 * or against a set of its own, and decides.
 *
 * @param dev      device
 * @param version  the revision byte, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null argument
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_poll_version(tmc2209_t *dev, uint8_t *version);

/**
 * @brief Reads any readable register off the device, uninterpreted.
 *
 * The path for MSCNT, MSCURACT, PWM_SCALE and PWM_AUTO, which carry no
 * condition worth naming, and for a diagnostic that dumps the whole device.
 * Does not update the cache.
 *
 * @param dev  device
 * @param reg  register to read
 * @param out  raw value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument, or a register not in the table
 * @retval TMC2209_ERR_ACCESS  write-only driver-side; there is nothing to read
 * @return any transport error from the read
 */
tmc2209_err_t tmc2209_poll_raw(tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);

/* ── Verdicts ───────────────────────────────────────────────────────────── */

/**
 * @brief Checks the cache against the driver for the registers that read back.
 *
 * Only GCONF and CHOPCONF can be checked, since the other eight owned
 * registers are write-only.
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
 * VACTUAL is write-only driver-side, so the value can only ever be checked
 * against the cache. That is authoritative while the slot is valid, and
 * TMC2209_DRIVER_RESET is what ends the guarantee.
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

/* ── Lines ──────────────────────────────────────────────────────────────── */

/**
 * @brief Gives the device its control lines.
 *
 * Separate from tmc2209_init() because it is optional. A configuration-only
 * caller, and the unit suite, never attach any, and every line call then
 * reports TMC2209_ERR_UNWIRED rather than needing a stub backend.
 *
 * @param dev    initialised device
 * @param lines  borrowed, must outlive @p dev. NULL detaches
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null device, or a backend without read/write
 */
tmc2209_err_t tmc2209_attach_lines(tmc2209_t *dev, const tmc2209_lines_t *lines);

/** @brief True when @p line is attached and this board connects it. */
bool tmc2209_line_is_wired(const tmc2209_t *dev, tmc2209_line_t line);

/**
 * @brief Reads the level presently on a line.
 *
 * Electrical, uninterpreted. An output answers with the level being driven,
 * which is what makes this the read-back after a write.
 *
 * This and IOIN observe the same pins from opposite ends of the trace, one
 * from the ESP32 and one from the driver, so a disagreement between them is
 * evidence neither reading can produce alone. See tmc2209_poll_pins().
 *
 * @param dev    device
 * @param line   line to read
 * @param level  the level, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null argument, or a line outside the enum
 * @retval TMC2209_ERR_UNWIRED  no backend, or this board does not connect it
 * @retval TMC2209_ERR_IO       the backend failed for its own reasons
 */
tmc2209_err_t tmc2209_line_read(const tmc2209_t *dev, tmc2209_line_t line, bool *level);

/**
 * @brief Drives a line to a level.
 *
 * Electrical and immediate: no polarity applied, no sequencing, no
 * preconditions checked. Driving STEP low then high is one microstep only if
 * each level was held for the part's minimum pulse width, which nothing here
 * measures and nothing here waits for.
 *
 * @param dev    device
 * @param line   an output line
 * @param level  level to drive
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG      null device, or a line outside the enum
 * @retval TMC2209_ERR_UNWIRED  no backend, or this board does not connect it
 * @retval TMC2209_ERR_ACCESS   the line is an input, in practice DIAG
 * @retval TMC2209_ERR_IO       the backend failed for its own reasons
 */
tmc2209_err_t tmc2209_line_write(tmc2209_t *dev, tmc2209_line_t line, bool level);

/**
 * @brief Enables or disables the power stage.
 *
 * ENN's polarity is a property of the part, so it is applied here and the
 * caller says what it wants rather than what level achieves it.
 *
 * Nothing is checked and nothing is refused. A driver whose CHOPCONF.toff is
 * zero enables and still holds no current, which is a fact worth learning from
 * a poll rather than from a rejected call.
 *
 * Worth knowing when reading DRV_STATUS afterwards: open load and cs_actual
 * describe a power stage that is driving. A disabled driver reports them
 * anyway, and they mean nothing.
 *
 * @param dev  device
 * @param on   true drives ENN low
 *
 * @return as tmc2209_line_write() for ENN
 */
tmc2209_err_t tmc2209_enable(tmc2209_t *dev, bool on);

/**
 * @brief Reads back whether the power stage is enabled.
 *
 * The ESP32's view. IOIN.enn is the driver's, and tmc2209_poll_pins() is how
 * to ask for it.
 *
 * @param dev  device
 * @param on   true when ENN is low, untouched on failure
 *
 * @return as tmc2209_line_read() for ENN
 */
tmc2209_err_t tmc2209_is_enabled(const tmc2209_t *dev, bool *on);

/* ── Cache validity ─────────────────────────────────────────────────────── */

/** @brief True when every owned slot is valid. False for a NULL device. */
bool tmc2209_all_owned_valid(const tmc2209_t *dev);

/**
 * @brief Invalidates every owned slot.
 *
 * Constant slots survive, since a brownout does not change the factory trim.
 * Callers that write through tmc2209_bus_send() must call this: a datagram the
 * library did not build is one it cannot account for.
 */
void tmc2209_invalidate_owned(tmc2209_t *dev);

/* ── Passthrough ────────────────────────────────────────────────────────── */

/**
 * @brief Sends raw bytes and optionally collects a fixed-length reply.
 *
 * Bytes in, bytes out, no interpretation. Keeps the lock and the echo
 * discipline, skips framing and the cache entirely. This is what the RPC
 * passthrough level and the HIL tier drive.
 *
 * Nothing about the reply is judged. A wrong CRC, a reply for a register that
 * was not asked about, and outright nonsense all come back as bytes, because
 * the caller here is diagnosing the driver and an opinion from this library
 * would be the thing under suspicion.
 *
 * Short replies are reported rather than discarded. @p rx_got says how many
 * bytes arrived, which separates nothing at all from something incomplete and
 * is what makes the bytes that did arrive safe to look at.
 *
 * @param bus     bus to drive; no device state is consulted or updated
 * @param tx      bytes to send, 1..32
 * @param tx_len  length of @p tx
 * @param rx      reply buffer, or NULL when @p rx_len is 0
 * @param rx_len  number of bytes to wait for; 0 to send only
 * @param rx_got  how many bytes arrived, 0..@p rx_len. Set on every return,
 *                including the failures that carry bytes. NULL to discard
 *
 * @retval TMC2209_OK              exactly @p rx_len bytes arrived
 * @retval TMC2209_ERR_ARG         null bus or tx, empty or oversized tx, rx_len
 *                                 without rx
 * @retval TMC2209_ERR_TX_TIMEOUT  the port took fewer bytes than it was given,
 *                                 so no reply was waited for
 * @retval TMC2209_ERR_RX_TIMEOUT  fewer than @p rx_len bytes came back.
 *                                 @p rx_got says how many did
 * @retval TMC2209_ERR_IO          the port failed for its own reasons
 * @retval TMC2209_ERR_ECHO        what came back is not what was sent, altered
 *                                 or short. The reply is still collected, so
 *                                 @p rx_got and @p rx remain worth reading
 */
tmc2209_err_t tmc2209_bus_send(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len, size_t *rx_got);

#endif /* TMC2209_H */
