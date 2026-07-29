/**
 * @file tmc2209.h
 * @brief The device object, and the component's public face.
 *
 * A TMC2209 is reached through three unrelated channels: a UART link carrying
 * register datagrams, four control lines, and a source of STEP pulses. Each has
 * its own backend header, and none of the three knows the other two exist. A
 * caller has one driver and wants one thing to call.
 *
 * That thing is @ref tmc2209_t. It carries the three backends, the driver's
 * address on the wire, and the register cache, so every call in the component
 * takes a device and no caller ever assembles an operation out of three parts.
 * Which is also what lets a call cross the subsystems that a backend cannot: a
 * move sets DIR on the lines, writes GCONF.shaft over UART, and only then
 * starts the pulse train.
 *
 * So the whole API is declared here, and implemented in one file per subsystem:
 * tmc2209_uart.c for transactions, tmc2209_lines.c for the lines,
 * tmc2209_stepgen.c for motion, and tmc2209.c for the device itself, meaning
 * lifecycle, registers and the cache. What the backend headers never mention is
 * @ref tmc2209_t, which is what keeps a backend implementable without ever
 * opening this header.
 *
 * Lifecycle: tmc2209_init(), then attach whichever backends the board has, then
 * tmc2209_bringup() to claim the driver and put a known configuration in it.
 * Attaching is optional per backend, and a configuration-only caller attaches
 * the uart alone.
 *
 * Not thread-safe: one device, one owner.
 */

#ifndef TMC2209_H
#define TMC2209_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tmc2209_err.h"
#include "tmc2209_lines.h"
#include "tmc2209_reg.h"
#include "tmc2209_stepgen.h"
#include "tmc2209_uart.h"

/** Element count of a configuration array literal. */
#define TMC2209_NELEM(a) (sizeof(a) / sizeof((a)[0]))

/** @brief One register and the value intended for it. The unit of tmc2209_write(). */
typedef struct {
    tmc2209_reg_t reg;
    uint32_t      value;
} tmc2209_regval_t;

/** @brief One driver, and everything known about what it currently holds. */
typedef struct {
    const tmc2209_uart_t *uart;          /**< register datagram channel, NULL until attached */
    const tmc2209_lines_t *lines;        /**< control lines, NULL until attached */
    const tmc2209_stepgen_t *stepgen;    /**< STEP pulse source, NULL until attached */
    uint8_t  addr;                       /**< 0..3, set by the MS1/MS2 straps */
    uint8_t  ifcnt;                      /**< last observed write counter */
    uint32_t cache[TMC2209_REG_COUNT];   /**< last known value per slot */
    uint32_t valid;                      /**< one bit per slot: device holds cache[slot] */
    bool     count_unread;               /**< a run was started and its final count has
                                              not been collected yet. See tmc2209_move() */
} tmc2209_t;

/**
 * @brief Construction only.
 *
 * Every register slot starts invalid and no backend is attached.
 *
 * @param dev   device to initialise; overwritten entirely
 * @param addr  0..3, matching the MS1/MS2 straps
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null device, or addr > 3
 */
tmc2209_err_t tmc2209_init(tmc2209_t *dev, uint8_t addr);

/**
 * @brief Gives the device the channel it speaks on.
 *
 * The wire is shared: one link carries up to four drivers, told apart by the
 * address handed to tmc2209_init(), so several devices attach the same @p uart
 * and inherit its timeout and retry policy along with it.
 *
 * @param dev   initialised device
 * @param uart  borrowed, must outlive @p dev. NULL detaches
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG  null device, or a backend missing tx or rx
 */
tmc2209_err_t tmc2209_attach_uart(tmc2209_t *dev, const tmc2209_uart_t *uart);

/**
 * @brief Claims a reachable driver and writes @p config to it.
 *
 * Probes the driver, seeds the IFCNT baseline, clears GSTAT, reads the
 * CONSTANT registers off this particular part, and writes the configuration.
 *
 * @p config must cover all @ref TMC2209_OWNED_COUNT owned registers. A partial
 * configuration is rejected.
 *
 * Returns with the driver holding @p config and standing still.
 *
 * GSTAT as found is handed back through @p at_bringup before it is cleared,
 * which is the only chance to see what the driver went through before this
 * firmware owned it. It says nothing about why the *controller* restarted;
 * that is esp_reset_reason()'s answer.
 *
 * @param dev         device with a uart attached
 * @param config      one entry per owned register, in any order
 * @param n           length of @p config
 * @param at_bringup  GSTAT as found, before it is cleared. NULL to discard
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG         null argument, or @p config does not cover
 *                                 every owned register, or it names a non-zero
 *                                 velocity
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
 * @retval TMC2209_ERR_ACCESS   @p config names a register that is not owned
 * @retval TMC2209_ERR_NO_ACK   IFCNT did not account for the writes issued
 * @return any transport error from the underlying reads and writes
 */
tmc2209_err_t tmc2209_bringup(tmc2209_t *dev,
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * `tmc2209_write()` covering the owned registers does that (see `tmc2209_bringup()`).
 *
 * @param dev         device
 * @param conditions  conditions to acknowledge; 0 does nothing and touches no wire
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG     null argument
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * @retval TMC2209_ERR_NO_BACKEND  no uart attached
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
 * Optional, and one set per driver. Every line call on a device without them
 * reports TMC2209_ERR_NO_BACKEND, so a configuration-only caller needs no stub
 * backend.
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
 * @retval TMC2209_ERR_ARG         null argument, or a line outside the enum
 * @retval TMC2209_ERR_NO_BACKEND  no lines backend attached
 * @retval TMC2209_ERR_UNWIRED     this board does not connect the line
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
 * @retval TMC2209_ERR_ARG         null device, or a line outside the enum
 * @retval TMC2209_ERR_NO_BACKEND  no lines backend attached
 * @retval TMC2209_ERR_UNWIRED     this board does not connect the line
 * @retval TMC2209_ERR_ACCESS   the line is an input, in practice DIAG, or it is
 *                              STEP on a device that has a stepgen attached and
 *                              therefore no longer owns the pin
 * @retval TMC2209_ERR_BUSY     DIR while a run is in flight. The odometer
 *                              records one direction per run, so a level
 *                              flipped mid-train would be counted as travel in
 *                              whichever direction the run started
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

/* ── Motion ─────────────────────────────────────────────────────────────── */

/**
 * @brief What one move is asked to do.
 *
 * @ref tmc2209_run_t plus the two bits a pulse source cannot know. DIR is a
 * line, STEP is a rate, and the two must agree before the first edge goes out,
 * which is the whole reason this struct exists rather than the caller driving
 * both backends itself.
 *
 * Both @p dir and @p shaft are stated rather than derived. The two together
 * decide which way the motor turns, and which of the four combinations winds
 * film forward depends on how the motor is mounted, so that mapping belongs
 * above. What this guarantees is that the stated pair is the pair in effect
 * when the first edge goes out.
 */
typedef struct {
    bool     dir;          /**< level to drive on DIR, electrical and uninterpreted */
    bool     shaft;        /**< GCONF.shaft this move was planned around. Written to the
                                driver when it holds the other value, so the pair always
                                takes effect together */
    uint32_t pulses;       /**< microsteps to emit. 0 runs until halted */
    uint32_t pullin_pps;   /**< rate of the first and last pulse */
    uint32_t cruise_pps;   /**< rate held between the ramps */
    uint32_t accel_pps_s;  /**< slope of both ramps. 0 only when cruise == pullin */
} tmc2209_move_t;

/**
 * @brief What the pulse source is doing, and what it has done.
 *
 * One run's worth. There is no odometer here and none in @ref tmc2209_t: with
 * no encoder on this machine, a position is a sum of run counts and nothing
 * more, and summing them is a decision about what the pulses meant. That
 * decision lives above, where the direction convention and the millimetres per
 * pulse already live.
 */
typedef struct {
    uint32_t emitted;    /**< pulses of the current run, or of the last one */
    uint32_t rate_pps;   /**< rate presently being emitted */
    bool     running;    /**< a run is in flight */
} tmc2209_motion_t;

/**
 * @brief Gives the device its source of STEP pulses.
 *
 * One per driver, like the lines and unlike the shared wire. Attaching one hands
 * STEP over: `tmc2209_line_write()` on STEP is refused from then on, because a
 * peripheral bound to a pin and a GPIO write to the same pin are two owners and
 * not two views.
 *
 * @param dev      initialised device, with no run in flight
 * @param stepgen  borrowed, must outlive @p dev. NULL detaches
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG   null device, a backend missing any of its four
 *                           calls, or one declaring max_pps of 0
 * @retval TMC2209_ERR_RATE  the backend cannot guarantee
 *                           @ref TMC2209_STEP_MIN_PULSE_NS
 * @retval TMC2209_ERR_BUSY  a run is in flight on the backend being replaced
 */
tmc2209_err_t tmc2209_attach_stepgen(tmc2209_t *dev, const tmc2209_stepgen_t *stepgen);

/**
 * @brief Whether pulses are presently going out.
 *
 * Asks the backend and reports, touching nothing else. This is what a
 * supervisor watches with: unlike tmc2209_get_motion_report() it does not
 * collect the count, so watching a run cannot consume the acknowledgement its
 * owner still owes.
 *
 * @param dev      device with a stepgen
 * @param running  true while a run is in flight, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG         null argument
 * @retval TMC2209_ERR_NO_BACKEND  no stepgen attached
 * @retval TMC2209_ERR_IO          the backend failed
 */
tmc2209_err_t tmc2209_is_running(const tmc2209_t *dev, bool *running);

/**
 * @brief Starts a move. Returns as soon as the pulses are on their way.
 *
 * Asynchronous, and the only call here that is. Sets DIR, then starts the
 * train, in that order and never the other. DIR stays the run's for as long as
 * the run lasts: tmc2209_line_write() on it is refused until the last pulse is
 * out. tmc2209_get_motion_report() is how the caller learns that happened.
 *
 * The previous run's count must have been collected first. A backend reports
 * one run at a time, so starting a second one overwrites the first one's total,
 * and pulses that went into film would be lost with nothing to show they
 * existed. That is TMC2209_ERR_UNREAD, and one tmc2209_get_motion_report() after the
 * run ends is what clears it.
 *
 * @p m.shaft is applied, not assumed: a driver holding the other value is
 * written first, which costs one verified datagram and costs nothing when it
 * already agrees. The cached GCONF has to be valid for that, since the
 * register's other bits would otherwise have to be invented. Refusing to move
 * rather than guessing is deliberate: with no encoder on this machine, a move
 * in the wrong direction is not detected, it is recorded as progress.
 *
 * A non-zero VACTUAL takes the driver off its STEP pin silently, so a move
 * would emit pulses that move nothing and still be counted. That is refused
 * when the cache knows the velocity, and not when it does not, because
 * inventing a refusal out of an invalid slot is worse than the check's absence.
 *
 * @param dev  device with a stepgen and DIR
 * @param m    what to move
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG          null argument, or a profile that does not
 *                                  describe a reachable ramp
 * @retval TMC2209_ERR_RATE         a rate above the backend's max_pps
 * @retval TMC2209_ERR_NO_BACKEND   no stepgen, or no lines for DIR
 * @retval TMC2209_ERR_UNWIRED      this board does not connect DIR
 * @retval TMC2209_ERR_BUSY         a run is already in flight
 * @retval TMC2209_ERR_UNREAD       the last run's count was never collected
 * @retval TMC2209_ERR_INVALID_SLOT GCONF is not cached, so the shaft bit cannot
 *                                  be set without inventing the rest of it
 * @retval TMC2209_ERR_ACCESS       VACTUAL is non-zero: the STEP pin is not
 *                                  what is driving this motor
 * @retval TMC2209_ERR_IO           the DIR write or the backend failed
 * @return any error from the GCONF write, when the shaft bit had to change
 */
tmc2209_err_t tmc2209_move(tmc2209_t *dev, const tmc2209_move_t *m);

/**
 * @brief Changes the cruise rate of a run in flight.
 *
 * What an unbounded run is for. Reel tension tracks radius, and radius changes
 * as film winds, so the rate has to move with it. Restarting the run to change
 * speed would put a stop and a start into a tension loop.
 *
 * Unlike tmc2209_move(), a rate below pullin_pps is accepted. Pull-in bounds
 * starting and stopping, not running: a motor already turning can be ramped
 * anywhere below it.
 *
 * @param dev         device with a run in flight
 * @param cruise_pps  new rate to ramp to, at the run's original accel
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG         null device
 * @retval TMC2209_ERR_RATE        zero, or above the backend's max_pps
 * @retval TMC2209_ERR_NO_BACKEND  no stepgen attached
 * @retval TMC2209_ERR_IDLE        nothing is running
 * @retval TMC2209_ERR_IO          the backend failed
 */
tmc2209_err_t tmc2209_retarget(tmc2209_t *dev, uint32_t cruise_pps);

/**
 * @brief Ends the run.
 *
 * Not an emergency stop. @p immediate still finishes the pulse in progress, and
 * the ramped form keeps stepping all the way down to pullin_pps. Anything
 * genuinely urgent drops the power stage with tmc2209_enable(), which is
 * synchronous and needs no peripheral to cooperate.
 *
 * The count is not collected here, because a ramped halt is still moving when
 * this returns and its final total is not known yet.
 * tmc2209_get_motion_report() is what collects it.
 *
 * Halting an idle driver succeeds and does nothing.
 *
 * @param dev        device
 * @param immediate  true cuts the train at the next pulse boundary
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG         null device
 * @retval TMC2209_ERR_NO_BACKEND  no stepgen attached
 * @retval TMC2209_ERR_IO          the backend failed
 */
tmc2209_err_t tmc2209_halt(tmc2209_t *dev, bool immediate);

/**
 * @brief Collects the run's pulse count, rate, and whether it is still going.
 *
 * Reaches the stepgen backend and nothing else. No datagram goes out, which is
 * why this is not one of the poll_ family: those are transactions with the
 * driver over UART, and this is a question for a peripheral on this side.
 *
 * Also the acknowledgement tmc2209_move() waits for. A call that finds the run
 * over hands its final count to the caller and clears the way for the next
 * move; one made mid-run reports progress and clears nothing, because the total
 * it would be acknowledging does not exist yet.
 *
 * Ask as often as the control loop likes. Nothing accumulates here, so the only
 * thing an extra call can change is that a finished run stops being owed.
 *
 * The count is pulses emitted, which is not the same as film moved. They agree
 * while the motor stays in sync, and TMC2209_DRIVER_RESET is the report that
 * they may no longer.
 *
 * @param dev  device
 * @param out  the run's count, rate and state
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG         null argument
 * @retval TMC2209_ERR_NO_BACKEND  no stepgen attached
 * @retval TMC2209_ERR_IO          the backend failed
 */
tmc2209_err_t tmc2209_get_motion_report(tmc2209_t *dev, tmc2209_motion_t *out);

/* ── Cache validity ─────────────────────────────────────────────────────── */

/** @brief True when every owned slot is valid. False for a NULL device. */
bool tmc2209_all_owned_valid(const tmc2209_t *dev);

/**
 * @brief Invalidates every owned slot.
 *
 * Constant slots survive, since a brownout does not change the factory trim.
 * Callers that write through tmc2209_uart_send() must call this: a datagram the
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
 * @param uart    channel to drive; no device state is consulted or updated
 * @param tx      bytes to send, 1..32
 * @param tx_len  length of @p tx
 * @param rx      reply buffer, or NULL when @p rx_len is 0
 * @param rx_len  number of bytes to wait for; 0 to send only
 * @param rx_got  how many bytes arrived, 0..@p rx_len. Set on every return,
 *                including the failures that carry bytes. NULL to discard
 *
 * @retval TMC2209_OK              exactly @p rx_len bytes arrived
 * @retval TMC2209_ERR_ARG         null uart or tx, empty or oversized tx, rx_len
 *                                 without rx
 * @retval TMC2209_ERR_TX_TIMEOUT  the backend took fewer bytes than it was given,
 *                                 so no reply was waited for
 * @retval TMC2209_ERR_RX_TIMEOUT  fewer than @p rx_len bytes came back.
 *                                 @p rx_got says how many did
 * @retval TMC2209_ERR_IO          the backend failed for its own reasons
 * @retval TMC2209_ERR_ECHO        what came back is not what was sent, altered
 *                                 or short. The reply is still collected, so
 *                                 @p rx_got and @p rx remain worth reading
 */
tmc2209_err_t tmc2209_uart_send(const tmc2209_uart_t *uart,
                                const uint8_t *tx, size_t tx_len,
                                uint8_t *rx, size_t rx_len, size_t *rx_got);

#endif /* TMC2209_H */
