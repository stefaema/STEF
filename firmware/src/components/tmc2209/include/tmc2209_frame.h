/**
 * @file tmc2209_frame.h
 * @brief The UART datagram format, as pure functions.
 *
 * Everything here is a function over byte arrays.
 * The three shapes, byte by byte:
 *
 * @verbatim
 * write         [0] sync  [1] slave addr  [2] reg|write  [3..6] value  [7] crc
 * read request  [0] sync  [1] slave addr  [2] reg                      [3] crc
 * reply         [0] sync  [1] master addr [2] reg        [3..6] value  [7] crc
 * @endverbatim
 *
 * A reply carries no slave address, so which driver answered is not a question
 * this layer can settle.
 */

#ifndef TMC2209_FRAME_H
#define TMC2209_FRAME_H

#include <stddef.h>
#include <stdint.h>

#include "tmc2209_err.h"

/* ── Fields ─────────────────────────────────────────────────────────────── */

/** Opens every datagram in either direction. */
#define TMC2209_SYNC          0x05U
/** Sync is the low nibble only; the reserved high nibble in a reply is masked out but still CRC'd. */
#define TMC2209_SYNC_MASK     0x0FU

/** Byte 1 of a reply, whichever driver sent it. */
#define TMC2209_MASTER_ADDR   0xFFU

/** The register index byte carries the direction: bit 7 set means write. */
#define TMC2209_WRITE_FLAG    0x80U
#define TMC2209_REG_MASK      0x7FU /**< the index, once direction is taken off */

/** Two bits of slave address, so up to four drivers may share one bus. */
#define TMC2209_ADDR_MASK     0x03U

#define TMC2209_WRITE_LEN     8U  /**< sync, addr, reg|write flag, 4 data, crc */
#define TMC2209_READ_REQ_LEN  4U  /**< sync, addr, reg, crc */
#define TMC2209_REPLY_LEN     8U  /**< sync, master addr, reg, 4 data, crc */

/* ── Datagrams ──────────────────────────────────────────────────────────── */

/**
 * @brief CRC-8/ATM, polynomial 0x07, LSB-first.
 *
 * Bits are fed low to high, matching the order a UART puts them on the wire.
 * Has to comply with the driver's datasheet.
 *
 * @param data  bytes to cover
 * @param len   how many, which for a datagram is every byte but its last: the
 *              CRC covers the message and not itself
 *
 * @return the check byte
 */
uint8_t tmc2209_crc8(const uint8_t *data, size_t len);

/**
 * @brief Lays out a write datagram, CRC included.
 *
 * The driver doesn't reply writes. ACK will have to live on a higher-level.
 *
 * @param out         filled entirely
 * @param slave_addr  0..3, masked to the two bits the bus carries
 * @param reg         register index; the write flag is added here
 * @param value       32 bits, most significant byte first
 */
void tmc2209_frame_write(uint8_t out[TMC2209_WRITE_LEN],
                         uint8_t slave_addr, uint8_t reg, uint32_t value);

/**
 * @brief Lays out a read request, CRC included.
 *
 * @param out         filled entirely
 * @param slave_addr  0..3, masked to the two bits the bus carries
 * @param reg         register index; the write flag is stripped here
 */
void tmc2209_frame_read_request(uint8_t out[TMC2209_READ_REQ_LEN],
                                uint8_t slave_addr, uint8_t reg);

/**
 * @brief Validates preamble, register and CRC before yielding a value.
 *
 * @param in          a full reply as received
 * @param expect_reg  the register the request named; the write flag is ignored
 * @param out         the yielded value, untouched on failure
 *
 * @retval TMC2209_OK
 * @retval TMC2209_ERR_ARG       null argument
 * @retval TMC2209_ERR_CRC       the bytes were corrupted in transit
 * @retval TMC2209_ERR_PREAMBLE  not a reply to this master, our own echoed
 *                               write being the usual reason
 * @retval TMC2209_ERR_REG       an intact reply about a register we did not ask
 *                               about, so the reply stream has slipped
 */
tmc2209_err_t tmc2209_frame_parse_reply(const uint8_t in[TMC2209_REPLY_LEN],
                                        uint8_t expect_reg, uint32_t *out);

#endif /* TMC2209_FRAME_H */
