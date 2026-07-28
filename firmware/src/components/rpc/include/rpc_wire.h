/**
 * @file rpc_wire.h
 * @brief Reads and writes the bytes of a frame, once, for both ends.
 *
 * A serialiser written on each side of a link is two implementations of one
 * agreement, and the second one drifts. This is the one implementation: the
 * firmware builds replies with it and the PC parses them with the same object
 * code, through cffi.
 *
 * Nothing here is a struct copied onto the wire. Every value is written with an
 * explicit width and an explicit byte order, so no padding rule, enum width or
 * ABI decision made by either compiler can change what a frame looks like.
 * Little-endian throughout, matching both the xtensa and the x86 the code runs
 * on, so the common case costs nothing.
 *
 * ## Errors are collected, not checked
 *
 * A frame is a dozen fields, and a bounds check after each one buries the
 * meaning of the code in error handling for a case that only happens when
 * something is already wrong. So a writer that overflows and a reader that runs
 * out both set @c ok to false and turn every later call into a no-op. The
 * caller checks once, at the end, and a partial frame is impossible: length is
 * only taken from a writer that finished.
 */

#ifndef RPC_WIRE_H
#define RPC_WIRE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "rpc_proto.h"

/** @brief Builds a frame body. Check @c ok before trusting @c len. */
typedef struct {
    uint8_t *buf;
    size_t   cap;
    size_t   len;
    bool     ok;  /**< false once anything did not fit */
} rpc_writer_t;

/** @brief Walks a frame body. Check @c ok after the last field. */
typedef struct {
    const uint8_t *buf;
    size_t         len;
    size_t         pos;
    bool           ok;  /**< false once anything ran past the end */
} rpc_reader_t;

/** @brief What a request frame says before its arguments. */
typedef struct {
    uint16_t id;      /**< echoed in the reply, so a late answer is recognisable */
    uint8_t  ns;      /**< @ref rpc_ns_t */
    uint8_t  method;  /**< numbering is per namespace */
} rpc_req_t;

/* ── Writing ────────────────────────────────────────────────────────────── */

void rpc_w_init(rpc_writer_t *w, uint8_t *buf, size_t cap);

void rpc_w_u8(rpc_writer_t *w, uint8_t v);
void rpc_w_u16(rpc_writer_t *w, uint16_t v);
void rpc_w_u32(rpc_writer_t *w, uint32_t v);
void rpc_w_i32(rpc_writer_t *w, int32_t v);
void rpc_w_bool(rpc_writer_t *w, bool v);

/** @brief Length-prefixed bytes: @c u16 count, then the bytes. */
void rpc_w_bytes(rpc_writer_t *w, const uint8_t *src, size_t len);

/** @brief Length-prefixed text, no terminator on the wire. NULL writes empty. */
void rpc_w_str(rpc_writer_t *w, const char *s);

/* ── Reading ────────────────────────────────────────────────────────────── */

void rpc_r_init(rpc_reader_t *r, const uint8_t *buf, size_t len);

uint8_t  rpc_r_u8(rpc_reader_t *r);
uint16_t rpc_r_u16(rpc_reader_t *r);
uint32_t rpc_r_u32(rpc_reader_t *r);
int32_t  rpc_r_i32(rpc_reader_t *r);
bool     rpc_r_bool(rpc_reader_t *r);

/**
 * @brief Borrows a length-prefixed byte string from the frame.
 *
 * Points into @p r's buffer, so it lives exactly as long as the frame does.
 *
 * @param r    reader
 * @param len  how many bytes, 0 on failure
 * @return pointer into the frame, or NULL on failure
 */
const uint8_t *rpc_r_bytes(rpc_reader_t *r, size_t *len);

/**
 * @brief True when every field read fit, and nothing is left over.
 *
 * Trailing bytes are an error because they mean the two ends disagree about
 * what this method takes, which is worth catching at the first call rather
 * than at the first field that happens to matter.
 */
bool rpc_r_done(const rpc_reader_t *r);

/* ── Frames ─────────────────────────────────────────────────────────────── */

/** @brief Starts a reply frame: type, id, status. Arguments follow. */
void rpc_frame_begin_rep(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint16_t id, rpc_status_t status);

/** @brief Starts a request frame: type, id, namespace, method. */
void rpc_frame_begin_req(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint16_t id, uint8_t ns, uint8_t method);

/** @brief Starts a log frame: type, level, uptime. Text follows. */
void rpc_frame_begin_log(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint8_t level, uint32_t uptime_ms);

/**
 * @brief Discards everything written after @p mark, and forgives an overflow.
 *
 * What a failed handler needs: the reply frame is built in place, so a method
 * that wrote half its return values before deciding it could not answer has to
 * take them back. Clearing @c ok is safe here precisely because the bytes that
 * overflowed are the ones being dropped.
 */
void rpc_w_rewind(rpc_writer_t *w, size_t mark);

/** @brief Overwrites the status of a reply frame already begun. */
void rpc_frame_set_status(rpc_writer_t *w, rpc_status_t status);

/**
 * @brief Appends the CRC and closes the frame.
 *
 * @return total length, or 0 if anything did not fit along the way. The only
 *         check the caller needs: a frame that was never fully written cannot
 *         report a length.
 */
size_t rpc_frame_finish(rpc_writer_t *w);

/**
 * @brief Verifies the CRC and points a reader at what the frame carries.
 *
 * @param buf  a decoded frame, CRC included
 * @param len  its length
 * @param type frame type, untouched on failure
 * @param r    positioned just after the type byte, on the header the type
 *             implies, and bounded so the CRC is not part of what it reads
 *
 * @return false if the frame is too short, the CRC disagrees, or the type is
 *         not one of @ref rpc_frame_t
 */
bool rpc_frame_open(const uint8_t *buf, size_t len, uint8_t *type, rpc_reader_t *r);

/**
 * @brief Reads the request header a @ref rpc_frame_open'd reader is sitting on.
 *
 * @return false if the header did not fit
 */
bool rpc_req_header(rpc_reader_t *r, rpc_req_t *out);

#endif /* RPC_WIRE_H */
