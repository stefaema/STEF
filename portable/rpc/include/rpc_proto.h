/**
 * @file rpc_proto.h
 * @brief What the two ends must agree on to exchange a frame at all.
 *
 * A frame kind, a size bound and the shape of a status byte are
 * properties of the transport.
 *
 * Nothing in this file may include anything but stdint and assert. It is
 * compiled for every side that speaks this RPC protocol, which is what
 * binds all to one definition.
 *
 * ## The layout rules, which hold for every struct on this wire
 *
 * A frame is `[header][payload][crc]`, and both the header and the payload are
 * plain structs read in place rather than fields decoded one at a time. Three
 * rules make that safe, and all three are load-bearing:
 *
 * 1. Every field sits at an offset that is a multiple of its own width, reached
 *    by explicit `_pad` members. Padding is declared, so no compiler is deciding it.
 * 2. Every header is exactly @ref RPC_HDR_LEN bytes, so the payload always
 *    begins at an offset divisible by 4 and its own fields stay aligned.
 * 3. Every struct asserts its own size, so a layout that drifts fails to compile
 *    on the end that drifted.
 *
 * Little-endian throughout.
 *
 */

#ifndef RPC_PROTO_H
#define RPC_PROTO_H

#include <assert.h>
#include <stdint.h>

/** Largest decoded frame: header, payload and CRC. */
#define RPC_MAX_FRAME 512

/** Every frame header is this long, which is what keeps a payload aligned. */
#define RPC_HDR_LEN 8U

/** CRC-16, little-endian, appended after the payload. */
#define RPC_CRC_LEN 2U

/** What is left for a payload once the header and the CRC have their share. */
#define RPC_MAX_PAYLOAD (RPC_MAX_FRAME - RPC_HDR_LEN - RPC_CRC_LEN)

/**
 * @brief How many namespaces the dispatch table holds.
 *
 * Capacity, not a count of what exists.
 *
 */
#define RPC_NS_MAX 8

/**
 * @brief Asserts that @p type occupies exactly @p n bytes on the wire.
 *
 * `static_assert` comes from `<assert.h>`, which is the one include this file
 * carries beyond stdint. It is checked while compiling and emits no code, and
 * `NDEBUG` does not reach it: that switch governs `assert`, not this.
 *
 * Everywhere the macro is used gets the include along with the macro, so a
 * caller declaring its own payloads never names assert at all.
 */
#define RPC_WIRE_SIZE(type, n) \
    static_assert(sizeof(type) == (n), #type " is not " #n " bytes on the wire")

/** @brief Which of the three kinds of frame this is. First byte, always. */
typedef enum {
    RPC_FRAME_REQ = 0, /**< inbound, asking for a method */
    RPC_FRAME_REP = 1, /**< outbound, answering a request */
    RPC_FRAME_LOG = 2, /**< outbound, unprompted. Payload is the text, no terminator */
} rpc_frame_t;

/* ── What a byte means ──────────────────────────────────────────────────── */

/**
 * Every field on this wire is a `uintN_t`, so the width says how much room a
 * value has and nothing says what kind of value it is. These name the kind.
 *
 * Each is an alias for a width, never an enum: an enum is `int`-sized and would
 * move the wire. A typedef carries kind, never bounds.
 */

/** @brief A truth value on the wire. */
typedef uint8_t rpc_bool_t;

/** @brief A @ref rpc_frame_t narrowed to a byte. */
typedef uint8_t rpc_frame_id_t;

/** @brief A namespace index, narrowed to a byte. */
typedef uint8_t rpc_ns_id_t;

/** @brief The log severity band: 1 error, 2 warn, 3 info, 4 debug, 5 verbose, 0 unknown. */
typedef uint8_t rpc_log_level_t;

/**
 * @brief What a reply reports, as one byte on the wire.
 *
 * A plain integer rather than an enum, because the values are shared out: the
 * ones below are the transport's own and everything else belongs to whoever
 * registers handlers. An enum would have to name all of them in one place,
 * which is the coupling this file exists without.
 *
 * One byte, split at @ref RPC_STATUS_TRANSPORT_BASE. Above the line the
 * transport answers for the value; below it the caller does. The transport
 * takes the narrow end because it has three statuses and will not grow, while
 * a caller's vocabulary follows whatever it drives.
 *
 * Values are fixed by the wire. Never renumber; append.
 */
typedef uint8_t rpc_status_t;

/* ── Headers ────────────────────────────────────────────────────────────── */
/*
 * The type byte leads all three, so a receiver can tell them apart before it
 * knows which struct it is holding. Everything after that is arranged for
 * alignment rather than for reading order.
 */

/** @brief What a request says before its arguments. */
typedef struct {
    rpc_frame_id_t type;    /**< @ref RPC_FRAME_REQ */
    rpc_ns_id_t    ns;      /**< namespace index */
    uint8_t        method;  /**< numbering is per namespace */
    uint8_t        _pad;
    uint16_t       id;      /**< echoed in the reply, so a late answer is recognisable */
    uint16_t       _pad2;
} rpc_req_hdr_t;
RPC_WIRE_SIZE(rpc_req_hdr_t, RPC_HDR_LEN);

/** @brief What a reply says before its return values. */
typedef struct {
    rpc_frame_id_t type;    /**< @ref RPC_FRAME_REP */
    rpc_status_t   status;
    uint8_t        _pad[2];
    uint16_t       id;      /**< the request this answers */
    uint16_t       _pad2;
} rpc_rep_hdr_t;
RPC_WIRE_SIZE(rpc_rep_hdr_t, RPC_HDR_LEN);

/** @brief What a log line says before its text. */
typedef struct {
    rpc_frame_id_t  type;   /**< @ref RPC_FRAME_LOG */
    rpc_log_level_t level;
    uint16_t        _pad;
    uint32_t        uptime_ms;
} rpc_log_hdr_t;
RPC_WIRE_SIZE(rpc_log_hdr_t, RPC_HDR_LEN);

/* ── Status ─────────────────────────────────────────────────────────────── */

/**
 * @brief Where the transport's statuses begin. Below this belongs to the caller.
 *
 * The split has to be enforced from the caller's side, since neither end of it
 * can see the other's names. This constant is the one thing both can refer to,
 * so a caller asserts its own statuses stay under it and the two vocabularies
 * share a byte without either listing the other.
 */
#define RPC_STATUS_TRANSPORT_BASE 240U

enum {
    RPC_OK = 0,

    /* The transport's own, for frames that never reach a handler. Append
       upward from the base; the space below it is not the transport's to use. */
    RPC_NO_METHOD = 240, /**< no such namespace, or no such method in it */
    RPC_BAD_FRAME = 241, /**< the payload is not the length this method takes */
    RPC_INTERNAL  = 242, /**< the responder failed for its own reasons */
};

static_assert(RPC_NO_METHOD >= RPC_STATUS_TRANSPORT_BASE,
              "the transport's statuses must sit at or above its own base");

#endif /* RPC_PROTO_H */
