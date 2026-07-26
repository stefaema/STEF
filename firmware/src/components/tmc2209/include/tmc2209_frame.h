/*
 * tmc2209_frame.h: the UART datagram format, as pure functions.
 *
 * No structs, no callbacks, no state, no I/O. Everything here is a function
 * over byte arrays, which is why it is where the unit tests bite hardest.
 */

#ifndef TMC2209_FRAME_H
#define TMC2209_FRAME_H

#include <stddef.h>
#include <stdint.h>

#include "tmc2209_err.h"

#define TMC2209_SYNC          0x05U
#define TMC2209_MASTER_ADDR   0xFFU

/* The register byte carries the direction: bit 7 set means write. Three
   functions build or inspect that byte and all of them have to agree, which
   is why this is a constant and the field widths below are not. */
#define TMC2209_WRITE_FLAG    0x80U
#define TMC2209_REG_MASK      0x7FU

/* Two bits of slave address, so up to four drivers share one bus. */
#define TMC2209_ADDR_MASK     0x03U

#define TMC2209_WRITE_LEN     8U  /* sync, addr, reg|write flag, 4 data, crc */
#define TMC2209_READ_REQ_LEN  4U  /* sync, addr, reg, crc */
#define TMC2209_REPLY_LEN     8U  /* sync, master addr, reg, 4 data, crc */

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
