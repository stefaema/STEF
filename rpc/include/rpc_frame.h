/**
 * @file rpc_frame.h
 * @brief Puts a header and a CRC around a payload, and takes them off again.
 *
 * This is the whole of the wire format's code. It knows a frame is
 * `[header][payload][crc]` and it knows nothing whatever about the payload,
 * which is a span of bytes to it and a struct to whoever asked for the call.
 *
 * The struct is the layout, and `rpc_proto.h` states the three rules that make
 * one safe to read in place.
 *
 * ## Building one
 *
 * The payload is written first, directly into the buffer at @ref rpc_payload,
 * and the header goes on afterwards because only then is the length known.
 * Nothing is copied and there is no intermediate.
 *
 *     rpc_buf_t buf;
 *     my_payload_t *p = rpc_payload(&buf);
 *     p->value = 7;
 *     size_t len = rpc_frame_seal_rep(&buf, id, RPC_OK, sizeof(*p));
 */

#ifndef RPC_FRAME_H
#define RPC_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "rpc_proto.h"

/**
 * @brief Storage for one frame, aligned so its structs may be read in place.
 *
 * Every header is read through its own type, and naming the three alternatives
 * here is what makes their alignment the compiler's problem.
 */
typedef union {
    rpc_req_hdr_t req;
    rpc_rep_hdr_t rep;
    rpc_log_hdr_t log;
    uint8_t       bytes[RPC_MAX_FRAME];
} rpc_buf_t;

/** @brief Where @p b's payload begins. Aligned for any field it will hold. */
static inline void *rpc_payload(rpc_buf_t *b)
{
    return &b->bytes[RPC_HDR_LEN];
}

/** @brief What @ref rpc_frame_open found. Points into the caller's buffer. */
typedef struct {
    uint8_t     type;         /**< @ref rpc_frame_t */
    const void *hdr;          /**< cast to the header @c type names */
    const void *payload;      /**< aligned, and empty when @c payload_len is 0 */
    size_t      payload_len;
} rpc_view_t;

/* ── Building ───────────────────────────────────────────────────────────── */

/*
 * Each of these writes the header over the first @ref RPC_HDR_LEN bytes of the
 * buffer, appends the CRC after @p payload_len bytes of payload, and reports
 * the total. The payload must already be in place.
 *
 * @return total frame length, or 0 if @p payload_len does not fit
 */

/** @brief Closes a request frame around a payload of arguments. */
size_t rpc_frame_seal_req(rpc_buf_t *b, uint16_t id, uint8_t ns, uint8_t method,
                          size_t payload_len);

/** @brief Closes a reply frame around a payload of return values. */
size_t rpc_frame_seal_rep(rpc_buf_t *b, uint16_t id, rpc_status_t status,
                          size_t payload_len);

/** @brief Closes a log frame around its text, which carries no terminator. */
size_t rpc_frame_seal_log(rpc_buf_t *b, uint8_t level, uint32_t uptime_ms,
                          size_t payload_len);

/* ── Reading ────────────────────────────────────────────────────────────── */

/**
 * @brief Says whether @p buf holds a frame, and where its parts are.
 *
 * Nothing is copied or decoded. @p out borrows @p buf, so it is valid only
 * while that buffer holds still, and a payload can become a struct by a cast the
 * caller could make.
 *
 * @param buf  a decoded frame, CRC included. Must be aligned, which is what
 *             @ref rpc_buf_t is for: the header is read through its own type
 * @param len  its length
 * @param out  untouched on failure
 *
 * @return false if the frame is too short or too long, the CRC disagrees, or
 *         the type is not one of @ref rpc_frame_t
 */
bool rpc_frame_open(const void *buf, size_t len, rpc_view_t *out);

#endif /* RPC_FRAME_H */
