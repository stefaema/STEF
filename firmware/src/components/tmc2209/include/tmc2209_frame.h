/*
 * tmc2209_frame.h: the UART datagram format, as pure functions.
 *
 * No structs, no callbacks, no state, no I/O. Everything here is a function
 * over byte arrays, which is why it is where the unit tests bite hardest.
 */

#ifndef TMC2209_FRAME_H
#define TMC2209_FRAME_H

#include "tmc2209_port.h"

#define TMC2209_SYNC          0x05u
#define TMC2209_MASTER_ADDR   0xFFu

#define TMC2209_WRITE_LEN     8u  /* sync, addr, reg|0x80, 4 data, crc */
#define TMC2209_READ_REQ_LEN  4u  /* sync, addr, reg, crc */
#define TMC2209_REPLY_LEN     8u  /* sync, 0xFF, reg, 4 data, crc */

/* CRC-8/ATM, polynomial 0x07, LSB-first. */
uint8_t tmc2209_crc8(const uint8_t *data, size_t len);

void tmc2209_frame_write(uint8_t out[TMC2209_WRITE_LEN],
                         uint8_t slave_addr, uint8_t reg, uint32_t value);

void tmc2209_frame_read_request(uint8_t out[TMC2209_READ_REQ_LEN],
                                uint8_t slave_addr, uint8_t reg);

/* Validates sync, master address, register and CRC before yielding a value.
   A non-OK return means *out is untouched. */
tmc2209_err_t tmc2209_frame_parse_reply(const uint8_t in[TMC2209_REPLY_LEN],
                                        uint8_t expect_reg, uint32_t *out);

#endif /* TMC2209_FRAME_H */
