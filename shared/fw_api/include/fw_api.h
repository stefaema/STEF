/**
 * @file fw_api.h
 * @brief What this firmware serves: namespaces, method numbers, payloads.
 *
 * Both ends compile this header, to avoid the PC and the firmware drifting on a
 * method number or a payload layout. The `rpc` component moves frames and knows
 * none of this.
 *
 * Every method's arguments and return values are a struct below, and the ABI
 * generator reads them from here. `rpc_proto.h` states the layout rules: no
 * packing, explicit `_pad` members, and every struct asserts its own size.
 *
 * Semantic typedefs say what a `uintN_t` holds. The wire's live in
 * `rpc_proto.h`, the driver's in the tmc2209 headers, and this board's here.
 *
 * Includes only stdint, rpc_proto.h and the freestanding tmc2209 headers, since
 * it is compiled for the ESP32 and for the host.
 */

#ifndef FW_API_H
#define FW_API_H

#include <stdint.h>

#include "rpc_proto.h"
#include "tmc2209_lines.h"
#include "tmc2209_reg.h"

/**
 * What the two ends check before trusting each other, as (backend, version).
 *
 * The backend names the implementation and the version its contract, since a
 * version alone cannot say whether the far end is ours. The backend carries no
 * chip model or driver count, as neither changes the contract.
 *
 * Bump the version on a change to a payload layout, method number or status
 * value, on a dev to main merge.
 */
#define FW_API_BACKEND "esp32-tmc2209"
#define FW_API_VERSION "0.1.0"

/** @brief Namespaces, by who assembles the bytes. */
typedef enum {
    RPC_NS_SYS   = 0, /**< about the firmware itself */
    RPC_NS_RELAY = 1, /**< the PC assembles the datagram */
    RPC_NS_RAW   = 2, /**< the firmware assembles it, from a register you name */
    RPC_NS_FILM  = 3, /**< the firmware assembles it, from an outcome you name */
    RPC_NS_COUNT = 4,
} rpc_ns_t;

/* ── Bounds ─────────────────────────────────────────────────────────────── */

/**
 * @brief Largest batch `raw.write` or `raw.bringup` will accept.
 *
 * Above the 23 registers, so one can be named twice. Fixed, to avoid allocating.
 */
#define RPC_MAX_OPS 32

/** @brief The part's longest datagram, both directions. */
#define RPC_RELAY_MAX_BYTES 32

/** @brief Most drivers one board can declare. Four addresses fit a wire. */
#define RPC_MAX_DEVICES 4

/** @brief Room for a driver's name in `sys.devices`, terminator included. */
#define RPC_NAME_MAX 16

/** @brief Room for one of `sys.version`'s strings, terminator included. */
#define RPC_STR_MAX 32

/* ── What a byte means here ─────────────────────────────────────────────── */
/* This board's own kinds. The rest are in the wire's headers or the driver's. */

/** @brief An index into the board's device table, as `sys.devices` reports it. */
typedef uint8_t rpc_dev_id_t;

/** @brief A @ref rpc_mode_t narrowed to a byte. */
typedef uint8_t rpc_mode_id_t;

/** @brief The reset reason the board booted with. */
typedef uint8_t rpc_reset_id_t;

/** @brief A @ref rpc_trip_reason_t narrowed to a byte. */
typedef uint8_t rpc_trip_reason_id_t;

/* ── Shared payload shapes ──────────────────────────────────────────────── */

/**
 * @brief A device index and nothing else, which is most of `raw`'s arguments.
 *
 * `sys.devices` says which index is which.
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
 * RPC_SYS_VERSION must answer before the versions are agreed, so its reply
 * shape never changes.
 */
typedef enum {
    RPC_SYS_VERSION = 0,
    RPC_SYS_STATE   = 1, /**< what the firmware is doing, and why it tripped */
    RPC_SYS_DEVICES = 2, /**< the board table: what exists and what it has */
    RPC_SYS_TRIP    = 3, /**< stop and release every drive, then refuse motion */
    RPC_SYS_UNTRIP  = 4, /**< allow motion again. The drives stay released */
    RPC_SYS_COUNT   = 5,
} rpc_sys_method_t;

/**
 * @brief What `sys.version` answers. Takes no arguments.
 *
 * Version and backend come first and are fixed width, so an end that disagrees
 * about everything after them can still read them. Nothing may be inserted
 * before them.
 *
 * The reset reason says whether the board rebooted.
 */
typedef struct {
    char           version[RPC_STR_MAX];
    char           backend[RPC_STR_MAX];
    char           idf[RPC_STR_MAX];
    rpc_reset_id_t reset_reason;
    uint8_t        _pad[3];
} rpc_sys_version_ret;
RPC_WIRE_SIZE(rpc_sys_version_ret, 100);

/**
 * @brief What `sys.state` answers. Takes no arguments.
 *
 * Reported only. The PC sets no mode except a trip, through `sys.trip`, and an
 * unsafe call is refused per call.
 */
typedef struct {
    uint32_t             uptime_ms;
    uint16_t             device_count;
    rpc_mode_id_t        mode;
    rpc_trip_reason_id_t trip_reason;  /**< RPC_TRIP_NONE unless the board is tripped */
    uint8_t              trip_detail;  /**< what `sys.trip` was given, else 0 */
    uint8_t              _pad[3];
} rpc_sys_state_ret;
RPC_WIRE_SIZE(rpc_sys_state_ret, 12);

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
 * What the board actually has, so a diagnostic can loop over it.
 */
typedef struct {
    uint32_t       count;
    rpc_dev_info_t devs[];
} rpc_sys_devices_ret;
RPC_WIRE_SIZE(rpc_sys_devices_ret, 4);

/**
 * @brief What `sys.trip` takes. Answers with the status alone.
 *
 * Every drive is halted and its VACTUAL set to 0, and ENN drops once nothing
 * moves. A board that is already tripped keeps its first reason.
 */
typedef struct {
    uint8_t    detail;     /**< kept for the PC to read back. The firmware gives it no meaning */
    rpc_bool_t immediate;  /**< halt at the next pulse instead of ramping down */
    uint8_t    _pad[2];
} rpc_sys_trip_args;
RPC_WIRE_SIZE(rpc_sys_trip_args, 4);

/**
 * @brief What `sys.untrip` answers. Takes no arguments.
 *
 * Refused with RPC_BUSY while a ramped halt is still running. The drives stay
 * released, so moving again starts with `raw.enable`.
 */
typedef struct {
    rpc_trip_reason_id_t reason;  /**< what was cleared, or RPC_TRIP_NONE */
    uint8_t              detail;
    uint8_t              _pad[2];
} rpc_sys_untrip_ret;
RPC_WIRE_SIZE(rpc_sys_untrip_ret, 4);

/* ── relay ──────────────────────────────────────────────────────────────── */

/**
 * @brief `relay` methods.
 *
 * One: put the caller's bytes on the wire unaltered.
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
 * @c outcome is a field, to avoid a failing status discarding the bytes that did
 * arrive. Silence or an altered echo is an answer here. The frame's status says
 * only whether the call was well formed.
 *
 * Only @c count bytes of @c rx are sent.
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
 * @brief `raw` methods, one per public library call, in `tmc2209.h`'s order.
 *
 * New methods are appended, to avoid redirecting an older PC's calls.
 */
typedef enum {
    RPC_RAW_READ             = 0,
    RPC_RAW_POLL_RAW         = 1,
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
    RPC_RAW_MOTION_REPORT    = 21,
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

typedef rpc_raw_read_args rpc_raw_poll_raw_args;
typedef rpc_raw_read_ret  rpc_raw_poll_raw_ret;

/** @brief A device, then @c count registers to write to it. */
typedef struct {
    rpc_dev_id_t idx;
    uint8_t      _pad[3];
    uint32_t     count;
    rpc_op_t     ops[];
} rpc_raw_write_args;
RPC_WIRE_SIZE(rpc_raw_write_args, 8);

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

/** @c usable comes with the number, since SG_RESULT outside the TCOOLTHRS
 *  window is noise. */
typedef struct {
    uint16_t   value;  /**< SG_RESULT, 0..510. Higher means less load */
    rpc_bool_t usable;
    uint8_t    _pad;
} rpc_raw_poll_load_ret;
RPC_WIRE_SIZE(rpc_raw_poll_load_ret, 4);

typedef rpc_dev_args rpc_raw_poll_pins_args;

/** IOIN as read. The PC decodes it with the same codec. */
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
 * Travels as a value, to avoid a failing status discarding the mask of slots
 * that disagree.
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

/** GSTAT as the driver held it, before bring-up cleared it. */
typedef struct {
    uint32_t gstat_found;
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
 * @brief A run, as the driver library takes it.
 *
 * A run outlives the call. Whoever starts it stops it, or a trip does.
 */
typedef struct {
    rpc_dev_id_t       idx;
    tmc2209_level_id_t dir;   /**< level to drive on DIR, electrical and uninterpreted */
    rpc_bool_t         shaft; /**< GCONF.shaft for this move */
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

typedef rpc_dev_args rpc_raw_motion_report_args;

typedef struct {
    uint32_t           emitted;  /**< pulses of the current run, or of the last one */
    uint32_t           rate_pps; /**< rate presently being emitted */
    rpc_bool_t         pulsing;
    tmc2209_level_id_t dir;      /**< DIR the counted run was started with */
    rpc_bool_t         shaft;    /**< GCONF.shaft the counted run was started with */
    uint8_t            _pad;
} rpc_raw_motion_report_ret;
RPC_WIRE_SIZE(rpc_raw_motion_report_ret, 12);

/* ── State and statuses ─────────────────────────────────────────────────── */

/** @brief What the firmware is doing. Reported by `sys.state`. */
typedef enum {
    RPC_MODE_IDLE     = 0, /**< nothing in flight. raw and relay are permitted */
    RPC_MODE_SCANNING = 1, /**< reserved for a scan. Nothing sets it yet */
    RPC_MODE_FAULT    = 2, /**< construction failed, so no device can be addressed */
    RPC_MODE_TRIPPED  = 3, /**< halted and released. Moving and enabling are refused */
} rpc_mode_t;

/** @brief Why the board tripped. */
typedef enum {
    RPC_TRIP_NONE      = 0, /**< not tripped */
    RPC_TRIP_KEEPALIVE = 1, /**< a drive was moving and no keepalive came in time */
    RPC_TRIP_REQUESTED = 2, /**< the PC called `sys.trip` */
} rpc_trip_reason_t;

/** @brief Why the board last booted. Same values as esp_reset_reason_t. */
typedef enum {
    RPC_RESET_UNKNOWN    = 0,
    RPC_RESET_POWERON    = 1,
    RPC_RESET_EXT        = 2,
    RPC_RESET_SW         = 3,
    RPC_RESET_PANIC      = 4,
    RPC_RESET_INT_WDT    = 5,
    RPC_RESET_TASK_WDT   = 6,
    RPC_RESET_WDT        = 7,
    RPC_RESET_DEEPSLEEP  = 8,
    RPC_RESET_BROWNOUT   = 9,
    RPC_RESET_SDIO       = 10,
    RPC_RESET_USB        = 11,
    RPC_RESET_JTAG       = 12,
    RPC_RESET_EFUSE      = 13,
    RPC_RESET_PWR_GLITCH = 14,
    RPC_RESET_CPU_LOCKUP = 15,
} rpc_reset_t;

/**
 * @brief What a handler in this image reports, on top of @ref rpc_status_t.
 *
 * The library's `TMC2209_ERR_*` names without the prefix, to avoid a second
 * vocabulary for the same events. The mapping is in rpc_status.c. They live here
 * and not with the transport because they follow the library.
 *
 * Values are fixed by the wire and differ from the library's enum. They stay
 * below @ref RPC_STATUS_TRANSPORT_BASE, which @ref RPC_STATUS_LAST asserts.
 * Never renumber; append.
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
    RPC_RATE         = 17, /**< a rate this stepgen cannot emit */

    /* This image's own, for a call the library never saw. */
    RPC_REFUSED      = 18, /**< policy: unsafe in the present state */

    /**
     * One past the last status this image serves. Not a wire value. The
     * assertion below uses it, to avoid this vocabulary growing into the
     * transport's.
     */
    RPC_STATUS_LAST
};

static_assert(RPC_STATUS_LAST <= RPC_STATUS_TRANSPORT_BASE,
              "handler statuses have grown into the transport's band");

/**
 * @brief Names a status, for a log line or an operator.
 *
 * Covers both the transport's statuses and this image's.
 *
 * @param status  any value, named here or not
 *
 * @return a static string, never NULL
 */
const char *rpc_strerror(rpc_status_t status);

#endif /* FW_API_H */
