/**
 * @file rpc_proto.h
 * @brief What the two ends must agree on to exchange a frame at all.
 *
 * Frame kinds, the size bound and the status byte. Includes only stdint and
 * assert, since every side that speaks this protocol compiles it.
 *
 * ## Layout rules, for every struct on this wire
 *
 * A frame is `[header][payload][crc]`, and headers and payloads are plain
 * structs read in place. That is safe because:
 *
 * 1. Every field sits at an offset that is a multiple of its own width, reached
 *    by explicit `_pad` members, to avoid the compiler choosing the padding.
 * 2. Every header is exactly @ref RPC_HDR_LEN bytes, so the payload begins at
 *    an offset divisible by 4 and its fields stay aligned.
 * 3. Every struct asserts its own size, so a layout that drifts fails to
 *    compile on the end that drifted.
 *
 * Little-endian throughout.
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

/** @brief How many namespaces the dispatch table can hold. */
#define RPC_NS_MAX 8

/**
 * @brief Asserts that @p type occupies exactly @p n bytes on the wire.
 *
 * Checked at compile time and unaffected by `NDEBUG`. Including this header
 * brings in `<assert.h>`, so a caller declaring payloads needs nothing else.
 */
#define RPC_WIRE_SIZE(type, n) \
    static_assert(sizeof(type) == (n), #type " is not " #n " bytes on the wire")

/** @brief Which kind of frame this is. First byte, always. */
typedef enum {
    RPC_FRAME_REQ       = 0, /**< inbound, asking for a method */
    RPC_FRAME_REP       = 1, /**< outbound, answering a request */
    RPC_FRAME_LOG       = 2, /**< outbound, unprompted. Payload is the text, no terminator */
    RPC_FRAME_KEEPALIVE = 3, /**< inbound, saying the caller is still there. Answered by a reply */
} rpc_frame_t;

/* ── What a byte means ──────────────────────────────────────────────────── */

/**
 * Every field on this wire is a `uintN_t`. These typedefs name what kind of
 * value a field holds.
 *
 * Each is an alias for a width and never an enum, to avoid an `int`-sized enum
 * moving the wire.
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
 * A plain integer, so the transport and whoever registers handlers can each own
 * part of the range without one enum naming both.
 *
 * Split at @ref RPC_STATUS_TRANSPORT_BASE: the transport's three statuses sit
 * above it, the caller's below.
 *
 * Values are fixed by the wire. Never renumber; append.
 */
typedef uint8_t rpc_status_t;

/* ── Headers ────────────────────────────────────────────────────────────── */
/*
 * The type byte leads every header, so a receiver can tell them apart first.
 * The rest is ordered for alignment.
 */

/** @brief What a request says before its arguments. */
typedef struct {
    rpc_frame_id_t type; /**< @ref RPC_FRAME_REQ */
    rpc_ns_id_t    ns; /**< namespace index */
    uint8_t        method; /**< numbering is per namespace */
    uint8_t        _pad;
    uint16_t       id; /**< echoed in the reply, so a late answer is recognisable */
    uint16_t       _pad2;
} rpc_req_hdr_t;
RPC_WIRE_SIZE(rpc_req_hdr_t, RPC_HDR_LEN);

/** @brief What a reply says before its return values. */
typedef struct {
    rpc_frame_id_t type; /**< @ref RPC_FRAME_REP */
    rpc_status_t   status;
    uint8_t        _pad[2];
    uint16_t       id; /**< the request this answers */
    uint16_t       keepalive_within_ms; /**< how soon the responder needs a keepalive, or
                                             @ref RPC_KEEPALIVE_NONE. Never 0 */
} rpc_rep_hdr_t;
RPC_WIRE_SIZE(rpc_rep_hdr_t, RPC_HDR_LEN);

/** The responder needs no keepalive. It is the field's largest value, so it also
    reads as the longest wait. */
#define RPC_KEEPALIVE_NONE 0xFFFFU

/** @brief What a keepalive says. It carries no payload. */
typedef struct {
    rpc_frame_id_t type; /**< @ref RPC_FRAME_KEEPALIVE */
    uint8_t        _pad[3];
    uint16_t       id; /**< echoed in the reply */
    uint16_t       _pad2;
} rpc_keepalive_hdr_t;
RPC_WIRE_SIZE(rpc_keepalive_hdr_t, RPC_HDR_LEN);

/** @brief What a log line says before its text. */
typedef struct {
    rpc_frame_id_t  type; /**< @ref RPC_FRAME_LOG */
    rpc_log_level_t level;
    uint16_t        _pad;
    uint32_t        uptime_ms;
} rpc_log_hdr_t;
RPC_WIRE_SIZE(rpc_log_hdr_t, RPC_HDR_LEN);

/* ── Status ─────────────────────────────────────────────────────────────── */

/**
 * @brief Where the transport's statuses begin. Below this belongs to the caller.
 *
 * A caller asserts its own statuses stay under this, so the two vocabularies
 * share a byte without either naming the other.
 */
#define RPC_STATUS_TRANSPORT_BASE 240U

enum {
    RPC_OK = 0,

    /* The transport's own, for frames that never reach a handler. Append upward
       from the base. */
    RPC_NO_METHOD = 240, /**< no such namespace, or no such method in it */
    RPC_BAD_FRAME = 241, /**< the payload is not the length this method takes */
    RPC_INTERNAL  = 242, /**< the responder failed for its own reasons */
};

static_assert(RPC_NO_METHOD >= RPC_STATUS_TRANSPORT_BASE,
              "the transport's statuses must sit at or above its own base");

#endif /* RPC_PROTO_H */
