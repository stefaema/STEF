/**
 * @file rpc_proto.h
 * @brief What the two ends must agree on to exchange a frame at all.
 *
 * Framing, not meaning. A frame kind, a size bound and the shape of a status
 * byte are properties of the transport, so they live with the transport and
 * both ends compile them.
 *
 * What is deliberately absent is every namespace, every method number and
 * every status a handler can produce. Those say what this firmware serves
 * rather than how a frame travels, so they live in `main/rpc_api.h` next to
 * the handlers that implement them. A component that named `raw.move` would be
 * a component that has to change when the library does.
 *
 * Nothing in this file may include anything but stdint. It is compiled once for
 * this firmware and again for the other side, which is what binds the two to one
 * definition.
 *
 * ## The layout rules, which hold for every struct on this wire
 *
 * A frame is `[header][payload][crc]`, and both the header and the payload are
 * plain structs read in place rather than fields decoded one at a time. Three
 * rules make that safe, and all three are load-bearing:
 *
 * 1. Nothing is packed. Every field sits at an offset that is a multiple of its
 *    own width, reached by explicit `_pad` members. A packed struct would put
 *    `uint32_t` at odd offsets, and an unaligned 32-bit load on xtensa is an
 *    exception rather than a slow read. Padding is declared so that no compiler
 *    is deciding it.
 * 2. Every header is exactly @ref RPC_HDR_LEN bytes, so the payload always
 *    begins at an offset divisible by 4 and its own fields stay aligned.
 * 3. Every struct on the wire carries a `_Static_assert` on its size, so a
 *    layout that drifts on either end fails to compile on the end that drifted.
 *
 * Little-endian throughout, matching both the xtensa and the x86 the code runs
 * on, so the common case costs nothing.
 */

#ifndef RPC_PROTO_H
#define RPC_PROTO_H

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
 * Capacity, not a count of what exists: the wire carries the namespace as a
 * byte and this only bounds a static table. What those numbers mean is
 * `rpc_api.h`'s answer.
 */
#define RPC_NS_MAX 8

/** @brief Asserts that @p type occupies exactly @p n bytes on the wire. */
#define RPC_WIRE_SIZE(type, n) \
    _Static_assert(sizeof(type) == (n), #type " is not " #n " bytes on the wire")

/** @brief Which of the three kinds of frame this is. First byte, always. */
typedef enum {
    RPC_FRAME_REQ = 0, /**< inbound, asking for a method */
    RPC_FRAME_REP = 1, /**< outbound, answering a request */
    RPC_FRAME_LOG = 2, /**< outbound, unprompted. Payload is the text, no terminator */
} rpc_frame_t;

/* ── Headers ────────────────────────────────────────────────────────────── */

/*
 * The type byte leads all three, so a receiver can tell them apart before it
 * knows which struct it is holding. Everything after that is arranged for
 * alignment rather than for reading order.
 */

/** @brief What a request says before its arguments. */
typedef struct {
    uint8_t  type;    /**< @ref RPC_FRAME_REQ */
    uint8_t  ns;      /**< @ref rpc_ns_t in rpc_api.h */
    uint8_t  method;  /**< numbering is per namespace */
    uint8_t  _pad;
    uint16_t id;      /**< echoed in the reply, so a late answer is recognisable */
    uint16_t _pad2;
} rpc_req_hdr_t;
RPC_WIRE_SIZE(rpc_req_hdr_t, RPC_HDR_LEN);

/** @brief What a reply says before its return values. */
typedef struct {
    uint8_t  type;    /**< @ref RPC_FRAME_REP */
    uint8_t  status;  /**< @ref rpc_status_t */
    uint8_t  _pad[2];
    uint16_t id;      /**< the request this answers */
    uint16_t _pad2;
} rpc_rep_hdr_t;
RPC_WIRE_SIZE(rpc_rep_hdr_t, RPC_HDR_LEN);

/** @brief What a log line says before its text. */
typedef struct {
    uint8_t  type;   /**< @ref RPC_FRAME_LOG */
    uint8_t  level;  /**< 1 error, 2 warn, 3 info, 4 debug, 5 verbose, 0 unknown */
    uint16_t _pad;
    uint32_t uptime_ms;
} rpc_log_hdr_t;
RPC_WIRE_SIZE(rpc_log_hdr_t, RPC_HDR_LEN);

/* ── Status ─────────────────────────────────────────────────────────────── */

/**
 * @brief What a reply reports, as one byte on the wire.
 *
 * A plain integer rather than an enum, because the values are shared out: the
 * three below are the transport's own and everything else belongs to whoever
 * registers handlers. An enum would have to name all of them in one place,
 * which is the coupling this file exists without.
 *
 * Values are fixed by the wire. Never renumber; append.
 */
typedef uint8_t rpc_status_t;

enum {
    RPC_OK        = 0,

    /* The transport's own, for frames that never reach a handler. Numbered
       from 32 so the handler vocabulary can grow underneath without ever
       colliding with these. */
    RPC_NO_METHOD = 32, /**< no such namespace, or no such method in it */
    RPC_BAD_FRAME = 33, /**< the payload is not the length this method takes */
    RPC_INTERNAL  = 35, /**< the firmware failed for its own reasons */
};

#endif /* RPC_PROTO_H */
