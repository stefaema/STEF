/**
 * @file fw_api.h
 * @brief What this firmware serves: namespaces, method numbers, payloads.
 *
 * The `rpc` component moves frames and is entitled to know nothing about what
 * they ask for. This is the other half of that split, and it lives in its own
 * module for the same reason `board.h` lives in `tmc2209_bind`: it names
 * drivers, registers and library calls, so it changes when this machine changes
 * and the transport does not.
 *
 * A method number is the third thing that would otherwise be written twice,
 * after register layouts and the framing itself. Written twice it drifts, and
 * the failure is silent: the PC asks for method 4 and the firmware runs the one
 * that used to be 4. So the numbering lives here, in a header both ends
 * compile, and neither end is entitled to its own copy.
 *
 * ## The payloads are here too, and that is the point
 *
 * Every method's arguments and return values are a struct below. Not a
 * convenience: it is the difference between a protocol you can read and one you
 * have to reconstruct by following the order of calls in a handler body. What a
 * method takes is a declaration, both ends compile it, and the PC's cffi build
 * parses this file rather than reimplementing it.
 *
 * `rpc_proto.h` states the three layout rules these structs obey. The short
 * version: nothing is packed, every field is naturally aligned by way of
 * explicit `_pad` members, and every struct asserts its own size.
 *
 * ## What a field means
 *
 * Semantic typedefs say what kind of value a `uintN_t` holds, and each lives
 * beside the thing it names: the wire's in `rpc_proto.h`, the driver's in the
 * tmc2209 headers, this board's here. So `raw`'s payloads name driver types
 * instead of restating them, `raw` being a projection of that library's API.
 *
 * Nothing in this file may include anything but stdint, rpc_proto.h and the
 * portable driver headers naming those types, all of them freestanding. It is
 * compiled for the ESP32 and again for the host, and read by the ABI generator.
 */

#ifndef FW_API_H
#define FW_API_H

#include <stdint.h>

#include "rpc_proto.h"
#include "tmc2209_lines.h"
#include "tmc2209_reg.h"

/**
 * What the two ends check before trusting each other. Bump on any change to a
 * payload layout, a method number, or a status value. Bounded to `sys.version`.
 *
 * Only bump on a dev to main merge. Nothing in between has shipped.
 */
#define RPC_PROTOCOL_VERSION 1

/** @brief Namespaces, by who assembles the bytes. */
typedef enum {
    RPC_NS_SYS   = 0, /**< about the firmware, not about a driver */
    RPC_NS_RELAY = 1, /**< the PC assembles the datagram */
    RPC_NS_RAW   = 2, /**< the firmware assembles it, from a register you name */
    RPC_NS_FILM  = 3, /**< the firmware assembles it, from an outcome you name */
    RPC_NS_COUNT = 4,
} rpc_ns_t;

/* ── Bounds ─────────────────────────────────────────────────────────────── */

/**
 * @brief Largest batch `raw.write` or `raw.bringup` will accept.
 *
 * A batch names registers, and there are 23 of them. Room to name one twice,
 * which the library allows, and a bound so the firmware needs no allocation.
 */
#define RPC_MAX_OPS 32

/** @brief The part's longest datagram, both directions. */
#define RPC_RELAY_MAX_BYTES 32

/** @brief Most drivers one board can declare, since four addresses fit a wire. */
#define RPC_MAX_DEVICES 4

/** @brief Room for a driver's name in `sys.devices`, terminator included. */
#define RPC_NAME_MAX 16

/** @brief Room for one of `sys.version`'s strings, terminator included. */
#define RPC_STR_MAX 32

/* ── What a byte means here ─────────────────────────────────────────────── */
/* This board's own kinds. Everything else a payload carries is spelled in the
   wire's headers or the driver's. */

/** @brief An index into the board's device table, as `sys.devices` reports it. */
typedef uint8_t rpc_dev_id_t;

/** @brief A @ref rpc_mode_t narrowed to a byte. */
typedef uint8_t rpc_mode_id_t;

/** @brief The reset reason the board booted with. */
typedef uint8_t rpc_reset_id_t;

/* ── Shared payload shapes ──────────────────────────────────────────────── */

/**
 * @brief A device index and nothing else, which is most of `raw`'s arguments.
 *
 * Devices are named by index into the board table. `sys.devices` is how a
 * client learns which index is which, and giving them prettier names is the
 * PC's job.
 */
typedef struct {
    rpc_dev_id_t idx;
    uint8_t      _pad[3];
} rpc_dev_args;
RPC_WIRE_SIZE(rpc_dev_args, 4);

/** @brief One register and the value to put in it, as a batch element. */
typedef struct {
    uint32_t         value;
    tmc2209_reg_id_t reg;
    uint8_t          _pad[3];
} rpc_op_t;
RPC_WIRE_SIZE(rpc_op_t, 8);

/* ── sys ────────────────────────────────────────────────────────────────── */

/**
 * @brief `sys` methods.
 *
 * RPC_SYS_VERSION is the one method that must answer on a link whose version
 * has not been agreed yet, so its reply shape can never change.
 */
typedef enum {
    RPC_SYS_VERSION = 0,
    RPC_SYS_STATE   = 1, /**< what the firmware is doing, and whether it is ready */
    RPC_SYS_DEVICES = 2, /**< the board table: what exists and what it has */
    RPC_SYS_COUNT   = 3,
} rpc_sys_method_t;

/**
 * @brief What `sys.version` answers. Takes no arguments.
 *
 * The protocol version leads and is fixed width, so a PC built against a
 * different protocol can read that field, decide it does not understand the
 * rest, and say so, which is the whole point of asking. Nothing may ever be
 * inserted before it.
 *
 * The strings are fixed rather than variable for the same reason. This reply
 * has to be readable by an end that disagrees about everything after it, and a
 * length-prefixed field is a thing that end would have to parse correctly to
 * find the field after it.
 *
 * The reset reason is here because the question a stale link raises first is
 * "did the board reboot", and answering it costs one byte.
 */
typedef struct {
    uint16_t       protocol;
    rpc_reset_id_t reset_reason;
    uint8_t        _pad;
    char           project[RPC_STR_MAX];
    char           version[RPC_STR_MAX];
    char           idf[RPC_STR_MAX];
} rpc_sys_version_ret;
RPC_WIRE_SIZE(rpc_sys_version_ret, 100);

/**
 * @brief What `sys.state` answers. Takes no arguments.
 *
 * Reported, never set. The PC does not announce that it is about to run
 * diagnostics; it asks what is happening and is refused per call if the answer
 * makes the call unsafe. So this is the whole of the mode system from the
 * outside: one question, no state to keep in sync across a link that can drop.
 */
typedef struct {
    uint32_t      uptime_ms;
    uint16_t      device_count;
    rpc_mode_id_t mode;
    rpc_bool_t    ready;
} rpc_sys_state_ret;
RPC_WIRE_SIZE(rpc_sys_state_ret, 8);

/** @brief One driver, as `sys.devices` reports it. */
typedef struct {
    char                name[RPC_NAME_MAX];
    uint8_t             addr;  /**< set by the MS1/MS2 straps */
    tmc2209_line_mask_t wired;
    rpc_bool_t          has_uart;
    rpc_bool_t          has_stepgen;
} rpc_dev_info_t;
RPC_WIRE_SIZE(rpc_dev_info_t, 20);

/**
 * @brief What `sys.devices` answers. Takes no arguments.
 *
 * What the board actually has, so a diagnostic loops over it instead of
 * hardcoding one driver. A bench board with one driver and the carrier with
 * three answer the same question, and the same script covers both.
 */
typedef struct {
    uint32_t       count;
    rpc_dev_info_t devs[];
} rpc_sys_devices_ret;
RPC_WIRE_SIZE(rpc_sys_devices_ret, 4);

/* ── relay ──────────────────────────────────────────────────────────────── */

/**
 * @brief `relay` methods.
 *
 * One, and there will only ever be one. The namespace exists to put bytes on
 * the wire unaltered, and a second method would be a second opinion.
 */
typedef enum {
    RPC_RELAY_SEND  = 0,
    RPC_RELAY_COUNT = 1,
} rpc_relay_method_t;

/** @brief The datagram to send, assembled by the caller and not examined. */
typedef struct {
    rpc_dev_id_t idx;
    uint8_t      reply_len; /**< bytes to wait for. 0 when the datagram has no reply */
    uint8_t      count;     /**< how many of @c tx follow */
    uint8_t      _pad;
    uint8_t      tx[];
} rpc_relay_send_args;
RPC_WIRE_SIZE(rpc_relay_send_args, 4);

/**
 * @brief What came back, and what the wire made of the attempt.
 *
 * @c outcome is a value rather than the frame's status because a driver that
 * stayed silent, or one whose echo came back altered, is an *answer* here and
 * not a failure. The bytes that did arrive are the evidence the caller asked
 * for, and a failing status would have dispatch discard them. The frame's
 * status then reports only whether the call was well formed, which is the one
 * thing this tier is still entitled to have an opinion about.
 *
 * Only @c count bytes of @c rx are sent, so the reply is as long as the answer
 * and no longer.
 */
typedef struct {
    rpc_status_t outcome; /**< of the transaction, not of the call */
    uint8_t      count;
    uint8_t      _pad[2];
    uint8_t      rx[RPC_RELAY_MAX_BYTES];
} rpc_relay_send_ret;
RPC_WIRE_SIZE(rpc_relay_send_ret, 36);

/* ── raw ────────────────────────────────────────────────────────────────── */

/**
 * @brief `raw` methods, one per public library call, in the header's order.
 *
 * The numbering is the wire's and the ordering is `tmc2209.h`'s, so a method
 * added to the library is appended here rather than inserted. Renumbering
 * would silently redirect an older PC's calls.
 */
typedef enum {
    RPC_RAW_READ             = 0,
    RPC_RAW_POLL             = 1,
    RPC_RAW_WRITE            = 2,
    RPC_RAW_POLL_HEALTH      = 3,
    RPC_RAW_CLEAR_FAULTS     = 4,
    RPC_RAW_POLL_LOAD        = 5,
    RPC_RAW_POLL_PINS        = 6,
    RPC_RAW_POLL_VERSION     = 7,
    RPC_RAW_VERIFY_CONFIG    = 8,
    RPC_RAW_SET_VELOCITY     = 9,
    RPC_RAW_SET_CURRENT      = 10,
    RPC_RAW_BRINGUP          = 11,
    RPC_RAW_ALL_OWNED_VALID  = 12,
    RPC_RAW_INVALIDATE_OWNED = 13,
    RPC_RAW_LINE_READ        = 14,
    RPC_RAW_LINE_WRITE       = 15,
    RPC_RAW_ENABLE           = 16,
    RPC_RAW_IS_ENABLED       = 17,
    RPC_RAW_MOVE             = 18,
    RPC_RAW_RETARGET         = 19,
    RPC_RAW_HALT             = 20,
    RPC_RAW_MOTION           = 21,
    RPC_RAW_COUNT            = 22,
} rpc_raw_method_t;

/* Registers. */

typedef struct {
    rpc_dev_id_t     idx;
    tmc2209_reg_id_t reg;
    uint8_t          _pad[2];
} rpc_raw_read_args;
RPC_WIRE_SIZE(rpc_raw_read_args, 4);

typedef struct {
    uint32_t value;
} rpc_raw_read_ret;
RPC_WIRE_SIZE(rpc_raw_read_ret, 4);

typedef rpc_raw_read_args rpc_raw_poll_args;
typedef rpc_raw_read_ret  rpc_raw_poll_ret;

/** @brief A device, then @c count registers to write to it. */
typedef struct {
    rpc_dev_id_t idx;
    uint8_t      _pad[3];
    uint32_t     count;
    rpc_op_t     ops[];
} rpc_raw_write_args;
RPC_WIRE_SIZE(rpc_raw_write_args, 8);

/**
 * @brief Where the library gave up, which is diagnostic only.
 *
 * Any failure invalidates every slot in the batch, including the ops
 * transmitted before it, because nothing is confirmed until the closing IFCNT
 * read. So this says where the library stopped, not where the state boundary
 * is, and it travels even on success for exactly that reason: it is never a
 * boundary to act on.
 */
typedef struct {
    uint16_t failed_at;
    uint16_t _pad;
} rpc_raw_write_ret;
RPC_WIRE_SIZE(rpc_raw_write_ret, 4);

/* Conditions and verdicts. */

typedef rpc_dev_args rpc_raw_poll_health_args;

typedef struct {
    tmc2209_condition_mask_t conditions;
} rpc_raw_poll_health_ret;
RPC_WIRE_SIZE(rpc_raw_poll_health_ret, 4);

typedef struct {
    rpc_dev_id_t             idx;
    uint8_t                  _pad[3];
    tmc2209_condition_mask_t conditions;
} rpc_raw_clear_faults_args;
RPC_WIRE_SIZE(rpc_raw_clear_faults_args, 8);

typedef rpc_dev_args rpc_raw_poll_load_args;

/** @c usable travels beside the number because SG_RESULT outside the TCOOLTHRS
 *  window is noise, and a control loop given only the number will act on it. */
typedef struct {
    uint16_t   value;  /**< SG_RESULT, 0..510. Higher means less load */
    rpc_bool_t usable;
    uint8_t    _pad;
} rpc_raw_poll_load_ret;
RPC_WIRE_SIZE(rpc_raw_poll_load_ret, 4);

typedef rpc_dev_args rpc_raw_poll_pins_args;

/** IOIN as it came off the wire. The PC decodes it with the same codec the
 *  firmware would have used, so decoding here would only cost a round trip. */
typedef struct {
    uint32_t value;
} rpc_raw_poll_pins_ret;
RPC_WIRE_SIZE(rpc_raw_poll_pins_ret, 4);

typedef rpc_dev_args rpc_raw_poll_version_args;

typedef struct {
    uint8_t version;
    uint8_t _pad[3];
} rpc_raw_poll_version_ret;
RPC_WIRE_SIZE(rpc_raw_poll_version_ret, 4);

typedef rpc_dev_args rpc_raw_verify_config_args;

/**
 * @brief Whether the device agrees with the cache, and where it does not.
 *
 * A disagreement is a result rather than a transport failure, and the caller
 * wants to know *which* slots disagree. A failing status would have the mask
 * discarded with the frame, so what the call found travels as a value. Same
 * shape as relay's outcome, for the same reason.
 */
typedef struct {
    tmc2209_slot_mask_t mismatched;
    rpc_bool_t          agrees;
    uint8_t             _pad[3];
} rpc_raw_verify_config_ret;
RPC_WIRE_SIZE(rpc_raw_verify_config_ret, 8);

/* Runtime writes. */

typedef struct {
    rpc_dev_id_t idx;
    uint8_t      _pad[3];
    int32_t      velocity;
} rpc_raw_set_velocity_args;
RPC_WIRE_SIZE(rpc_raw_set_velocity_args, 8);

typedef struct {
    rpc_dev_id_t idx;
    uint8_t      ihold;      /**< 0..31 */
    uint8_t      irun;       /**< 0..31 */
    uint8_t      iholddelay; /**< 0..15 */
} rpc_raw_set_current_args;
RPC_WIRE_SIZE(rpc_raw_set_current_args, 4);

/* Bring-up and cache. */

typedef rpc_raw_write_args rpc_raw_bringup_args;

/** GSTAT as found is the only look anyone gets at what the driver went through
 *  before this firmware owned it, so it travels even though bring-up clears it. */
typedef struct {
    uint32_t gstat_at_bringup;
} rpc_raw_bringup_ret;
RPC_WIRE_SIZE(rpc_raw_bringup_ret, 4);

typedef rpc_dev_args rpc_raw_all_owned_valid_args;

typedef struct {
    rpc_bool_t valid;
    uint8_t    _pad[3];
} rpc_raw_all_owned_valid_ret;
RPC_WIRE_SIZE(rpc_raw_all_owned_valid_ret, 4);

typedef rpc_dev_args rpc_raw_invalidate_owned_args;

/* Lines. */

typedef struct {
    rpc_dev_id_t      idx;
    tmc2209_line_id_t line;
    uint8_t           _pad[2];
} rpc_raw_line_read_args;
RPC_WIRE_SIZE(rpc_raw_line_read_args, 4);

typedef struct {
    tmc2209_level_id_t level;
    uint8_t            _pad[3];
} rpc_raw_line_read_ret;
RPC_WIRE_SIZE(rpc_raw_line_read_ret, 4);

typedef struct {
    rpc_dev_id_t       idx;
    tmc2209_line_id_t  line;
    tmc2209_level_id_t level;
    uint8_t            _pad;
} rpc_raw_line_write_args;
RPC_WIRE_SIZE(rpc_raw_line_write_args, 4);

typedef struct {
    rpc_dev_id_t idx;
    rpc_bool_t   on;
    uint8_t      _pad[2];
} rpc_raw_enable_args;
RPC_WIRE_SIZE(rpc_raw_enable_args, 4);

typedef rpc_dev_args rpc_raw_is_enabled_args;

typedef struct {
    rpc_bool_t on;
    uint8_t    _pad[3];
} rpc_raw_is_enabled_ret;
RPC_WIRE_SIZE(rpc_raw_is_enabled_ret, 4);

/* Motion. */

/**
 * @brief A run, exactly as the driver library takes it.
 *
 * A run outlives the call that started it and nothing on the board ends it on
 * the caller's behalf, so whoever starts one owns stopping it.
 */
typedef struct {
    rpc_dev_id_t       idx;
    tmc2209_level_id_t dir;   /**< level to drive on DIR, electrical and uninterpreted */
    rpc_bool_t         shaft; /**< GCONF.shaft this move was planned around */
    uint8_t            _pad;
    uint32_t           pulses;      /**< microsteps to emit. 0 runs until halted */
    uint32_t           pullin_pps;  /**< rate of the first and last pulse */
    uint32_t           cruise_pps;  /**< rate held between the ramps */
    uint32_t           accel_pps_s; /**< slope of both ramps */
} rpc_raw_move_args;
RPC_WIRE_SIZE(rpc_raw_move_args, 20);

typedef struct {
    rpc_dev_id_t idx;
    uint8_t      _pad[3];
    uint32_t     cruise_pps;
} rpc_raw_retarget_args;
RPC_WIRE_SIZE(rpc_raw_retarget_args, 8);

typedef struct {
    rpc_dev_id_t idx;
    rpc_bool_t   immediate;
    uint8_t      _pad[2];
} rpc_raw_halt_args;
RPC_WIRE_SIZE(rpc_raw_halt_args, 4);

typedef rpc_dev_args rpc_raw_motion_args;

typedef struct {
    uint32_t           emitted;  /**< pulses of the current run, or of the last one */
    uint32_t           rate_pps; /**< rate presently being emitted */
    rpc_bool_t         running;
    tmc2209_level_id_t dir;      /**< DIR the counted run was started with */
    rpc_bool_t         shaft;    /**< GCONF.shaft the counted run was started with */
    uint8_t            _pad;
} rpc_raw_motion_ret;
RPC_WIRE_SIZE(rpc_raw_motion_ret, 12);

/* ── State and statuses ─────────────────────────────────────────────────── */

/** @brief What the firmware is doing. Reported by `sys.state`, never set. */
typedef enum {
    RPC_MODE_IDLE     = 0, /**< nothing in flight. raw and relay are permitted */
    RPC_MODE_SCANNING = 1, /**< a run owns the transport; raw and relay are refused */
    RPC_MODE_FAULT    = 2, /**< construction failed, so no device can be addressed */
} rpc_mode_t;

/**
 * @brief What a handler in this image reports, on top of @ref rpc_status_t.
 *
 * The library's `TMC2209_ERR_*` names with the prefix dropped, because raw is a
 * projection of that API and inventing a second error vocabulary would mean
 * translating between two sets of names that describe the same events. The
 * mapping is in rpc_status.c, firmware-side; the PC only ever sees these.
 *
 * That correspondence is also why these live here and not with the transport:
 * they follow the library, and the transport must not.
 *
 * Values are fixed by the wire and are not the library's enum values. They live
 * below @ref RPC_STATUS_TRANSPORT_BASE, and @ref RPC_STATUS_LAST is what holds
 * them there. Never renumber; append.
 */
/* clang-format off */
enum { /* NOLINT(readability-enum-initial-value): RPC_STATUS_LAST must follow, never pin */
    RPC_ARG          = 1,  /**< caller passed something impossible */
    RPC_TX_TIMEOUT   = 2,
    RPC_RX_TIMEOUT   = 3,  /**< the driver stayed silent */
    RPC_IO           = 4,  /**< the UART peripheral failed */
    RPC_ECHO         = 5,  /**< something else drove the line */
    RPC_SYNC         = 6,  /**< reply sync byte or master address wrong */
    RPC_CRC          = 7,
    RPC_REG          = 8,  /**< a reply for a register we did not ask about */
    RPC_NO_ACK       = 9,  /**< IFCNT did not account for the writes issued */
    RPC_ACCESS       = 10, /**< the register or line access policy forbids this */
    RPC_NO_BACKEND   = 11, /**< nothing attached to carry the call out */
    RPC_UNWIRED      = 12, /**< the line is not connected on this board */
    RPC_INVALID_SLOT = 13, /**< the cached value cannot be believed */
    RPC_MISMATCH     = 14, /**< the device disagrees with the cache */
    RPC_BUSY         = 15, /**< a run is in flight and this would disturb it */
    RPC_IDLE         = 16, /**< no run is in flight and this needs one */
    RPC_RATE         = 17, /**< a rate beyond what this stepgen can emit */

    /* This image's own, for a call the library never got to see. */
    RPC_REFUSED      = 18, /**< policy: unsafe in the present state */

    /**
     * One past the last status this image serves. A marker for the assertion
     * below, never a value on the wire: appending above it is what would push
     * this vocabulary into the transport's, and that has to fail loudly rather
     * than produce a reply the other end reads as a framing error.
     */
    RPC_STATUS_LAST
};

static_assert(RPC_STATUS_LAST <= RPC_STATUS_TRANSPORT_BASE,
              "handler statuses have grown into the transport's band");

/**
 * @brief Names a status, for a log line or an operator.
 *
 * Both bands in one call. @ref rpc_proto.h keeps the transport's statuses and
 * the caller's apart on purpose and neither is entitled to list the other, but
 * this file already names both, so the strings cost no coupling that the
 * numbering has not already paid for.
 *
 *
 * @param status  any value, named here or not
 *
 * @return a static string, never NULL, so it drops straight into a %s
 */
const char *rpc_strerror(rpc_status_t status);

#endif /* RPC_API_H */
