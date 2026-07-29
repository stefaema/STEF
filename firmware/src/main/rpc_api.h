/**
 * @file rpc_api.h
 * @brief What this firmware serves: namespaces, method numbers, statuses.
 *
 * The `rpc` component moves frames and is entitled to know nothing about what
 * they ask for. This is the other half of that split, and it belongs to `main`
 * for the same reason `board.h` does: it names drivers, registers and library
 * calls, so it changes when this machine changes and the transport does not.
 *
 * A method number is the third thing that would otherwise be written twice,
 * after register layouts and the framing itself. Written twice it drifts, and
 * the failure is silent: the PC asks for method 4 and the firmware runs the one
 * that used to be 4. So the numbering lives here, in a header both ends
 * compile, and neither end is entitled to its own copy.
 *
 * Nothing in this file may include anything but stdint and rpc_proto.h. It is
 * compiled for the ESP32 and again for the host, and it is what the PC's cffi
 * build reads alongside the component's header.
 */

#ifndef RPC_API_H
#define RPC_API_H

#include <stdint.h>

#include "rpc_proto.h"

/**
 * What the two ends check before trusting each other. Bump on any change to a
 * frame layout, a method number, or a status value. `sys.version` is what makes
 * the mismatch a clean rejection at connect time rather than a decode that
 * succeeds and lies.
 */
#define RPC_PROTOCOL_VERSION 1

/** @brief Namespaces, by who assembles the bytes. See docs/README.md. */
typedef enum {
    RPC_NS_SYS         = 0, /**< about the firmware, not about a driver */
    RPC_NS_PASSTHROUGH = 1, /**< the PC assembles the datagram */
    RPC_NS_RAW         = 2, /**< the firmware assembles it, from a register you name */
    RPC_NS_SMART       = 3, /**< the firmware assembles it, from an outcome you name */
    RPC_NS_COUNT       = 4,
} rpc_ns_t;

/**
 * @brief `sys` methods.
 *
 * RPC_SYS_VERSION is the one method that must answer on a link whose version
 * has not been agreed yet, so its reply shape can never change: a `u16`
 * protocol version first, and anything after it is optional to the reader.
 */
typedef enum {
    RPC_SYS_VERSION = 0,
    RPC_SYS_STATE   = 1, /**< what the firmware is doing, and whether it is ready */
    RPC_SYS_DEVICES = 2, /**< the board table: what exists and what it has */
    RPC_SYS_COUNT   = 3,
} rpc_sys_method_t;

/**
 * @brief `passthrough` methods.
 *
 * One, and there will only ever be one. The namespace exists to put bytes on
 * the wire unaltered, and a second method would be a second opinion.
 */
typedef enum {
    RPC_PT_SEND  = 0,
    RPC_PT_COUNT = 1,
} rpc_pt_method_t;

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

/**
 * @brief Largest batch `raw.write` or `raw.bringup` will accept.
 *
 * A batch names registers, and there are 23 of them. Room to name one twice,
 * which the library allows, and a bound so the firmware needs no allocation.
 */
#define RPC_MAX_OPS 32

/** @brief What the firmware is doing. Reported by `sys.state`, never set. */
typedef enum {
    RPC_MODE_IDLE     = 0, /**< nothing in flight. raw and passthrough are permitted */
    RPC_MODE_SCANNING = 1, /**< a scan owns the transport; raw and passthrough are refused */
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
 * Values are fixed by the wire and are not the library's enum values. They stay
 * clear of the transport's own, which start at 32. Never renumber; append.
 */
enum {
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
    RPC_REFUSED      = 34, /**< policy: unsafe in the present state */
};

#endif /* RPC_API_H */
