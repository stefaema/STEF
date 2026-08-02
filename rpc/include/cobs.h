/**
 * @file cobs.h
 * @brief Turns a frame into a run of bytes that contains no zero.
 *
 * A byte stream has no boundaries, so a receiver needs some byte to mean "the
 * frame ends here". Any byte that is picked could also occur inside the payload.
 *
 * COBS removes the problem instead of managing it: the encoding is guaranteed
 * to contain no zero byte at all, so a zero in the stream means end-of-frame
 * and can mean nothing else.
 *
 * Neither function writes the delimiter. Framing is the caller's, so the caller
 * appends the zero.
 */

#ifndef COBS_H
#define COBS_H

#include <stddef.h>
#include <stdint.h>

/** Worst case encoded length for @p n bytes, delimiter not included. */
#define COBS_ENCODED_MAX(n) ((n) + ((n) / 254U) + 1U)

/**
 * @brief Encodes @p len bytes so that none of the output is zero.
 *
 * @param src  bytes to encode
 * @param len  how many
 * @param dst  output, at least COBS_ENCODED_MAX(len) bytes
 * @param cap  size of @p dst
 *
 * @return bytes written, or 0 if @p dst is too small. Never returns 0 on
 *         success: even an empty input encodes to one byte.
 */
size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst, size_t cap);

/**
 * @brief Recovers the frame from one delimited run.
 *
 * @p src is the bytes between two delimiters, the delimiters excluded.
 *
 * @param src  encoded bytes, no zero among them
 * @param len  how many
 * @param dst  output, at least @p len bytes
 * @param cap  size of @p dst
 *
 * @return bytes written, or 0 if the input is malformed: a zero inside it, a
 *         group running past the end, or output beyond @p cap. Garbage that
 *         happens to decode is caught by the CRC, not here.
 */
size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst, size_t cap);

#endif /* COBS_H */
