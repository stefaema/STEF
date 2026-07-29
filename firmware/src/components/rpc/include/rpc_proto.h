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
 */

#ifndef RPC_PROTO_H
#define RPC_PROTO_H

#include <stdint.h>

/** Largest decoded frame: header, payload and CRC. */
#define RPC_MAX_FRAME 512

/**
 * @brief How many namespaces the dispatch table holds.
 *
 * Capacity, not a count of what exists: the wire carries the namespace as a
 * byte and this only bounds a static table. What those numbers mean is
 * `rpc_api.h`'s answer.
 */
#define RPC_NS_MAX 8

/** @brief Which of the three kinds of frame this is. First byte, always. */
typedef enum {
    RPC_FRAME_REQ = 0, /**< inbound. `u16 id`, `u8 ns`, `u8 method`, args */
    RPC_FRAME_REP = 1, /**< outbound, answering a request. `u16 id`, `u8 status`, return values */
    RPC_FRAME_LOG = 2, /**< outbound, unprompted. `u8 level`, `u32 uptime_ms`, text */
} rpc_frame_t;

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
    RPC_BAD_FRAME = 33, /**< arguments ran out, or trailing bytes remain */
    RPC_INTERNAL  = 35, /**< the firmware failed for its own reasons */
};

#endif /* RPC_PROTO_H */
