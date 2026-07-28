#include "crc16.h"

/*
 * Bitwise rather than table-driven. A 512-byte table would save microseconds on
 * frames that are a few hundred bytes long, on a link whose round trip is
 * measured in milliseconds. Nothing here is on the cadence path.
 */

uint16_t crc16_ccitt(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFu;

    if (data == NULL) {
        return crc;
    }

    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);

        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000u) ? (uint16_t)((uint16_t)(crc << 1) ^ 0x1021u)
                                  : (uint16_t)(crc << 1);
        }
    }

    return crc;
}
