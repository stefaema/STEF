/**
 * @file crc16.h
 * @brief The check that tells a well-formed frame from a plausible one.
 *
 * COBS says where a frame ends, not whether it survived the trip.
 *
 * CRC-16/CCITT-FALSE: polynomial 0x1021, initial value 0xFFFF, no reflection,
 * no final xor.
 *
 */

#ifndef CRC16_H
#define CRC16_H

#include <stddef.h>
#include <stdint.h>

/** @brief CRC-16/CCITT-FALSE over @p len bytes. */
uint16_t crc16_ccitt(const uint8_t *data, size_t len);

#endif /* CRC16_H */
