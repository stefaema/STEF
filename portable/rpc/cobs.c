#include "cobs.h"

/*
 * The encoding is a chain of groups. Each group is a code byte followed by the
 * non-zero bytes that come after it, and the code says how far the next code
 * byte is. A code of n means n-1 data bytes and then a zero that was removed;
 * a code of 0xFF is the exception, meaning 254 data bytes and no zero, which is
 * what caps the overhead at one byte per 254.
 *
 * The code byte cannot be written until its group is finished, so the writer
 * reserves its slot and fills it in on the way past.
 */

size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst, size_t cap)
{
    if (src == NULL || dst == NULL || cap < COBS_ENCODED_MAX(len)) {
        return 0;
    }

    size_t  code_at = 0; /* reserved slot for the group being built */
    size_t  out     = 1;
    uint8_t code    = 1;

    for (size_t i = 0; i < len; i++) {
        if (src[i] == 0) {
            dst[code_at] = code;
            code_at      = out++;
            code         = 1;
            continue;
        }

        dst[out++] = src[i];
        code++;

        if (code == 0xFF) { /* group is full; start another */
            dst[code_at] = code;
            code_at      = out++;
            code         = 1;
        }
    }

    dst[code_at] = code;
    return out;
}

size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst, size_t cap)
{
    if (src == NULL || dst == NULL) {
        return 0;
    }

    size_t out = 0;
    size_t i   = 0;

    while (i < len) {
        uint8_t code = src[i++];
        if (code == 0) {
            return 0; /* a delimiter inside the frame: not our encoding */
        }

        size_t n = (size_t)code - 1U;
        if (i + n > len || out + n > cap) {
            return 0;
        }

        for (size_t k = 0; k < n; k++) {
            dst[out++] = src[i++];
        }

        /*
         * The removed zero is put back, except after a full group, which stood
         * for no zero, and except at the end, where the last code closes the
         * chain rather than standing in for anything.
         */
        if (code != 0xFF && i < len) {
            if (out >= cap) {
                return 0;
            }
            dst[out++] = 0;
        }
    }

    return out;
}
