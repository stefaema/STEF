#include "tmc2209_frame.h"

uint8_t tmc2209_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        uint8_t byte = data[i];
        for (int bit = 0; bit < 8; bit++) {
            if ((crc >> 7) ^ (byte & 0x01)) {
                crc = (uint8_t)((crc << 1) ^ 0x07);
            } else {
                crc = (uint8_t)(crc << 1);
            }
            byte >>= 1;
        }
    }
    return crc;
}

void tmc2209_frame_write(uint8_t out[TMC2209_WRITE_LEN],
                         uint8_t slave_addr, uint8_t reg, uint32_t value)
{
    /* Write commands need 8 bytes and send back no reply */

    out[0] = TMC2209_SYNC;
    out[1] = (uint8_t)(slave_addr & TMC2209_ADDR_MASK);
    out[2] = (uint8_t)(reg | TMC2209_WRITE_FLAG);
    out[3] = (uint8_t)(value >> 24);
    out[4] = (uint8_t)(value >> 16);
    out[5] = (uint8_t)(value >> 8);
    out[6] = (uint8_t)(value >> 0);
    out[7] = tmc2209_crc8(out, 7);
}

void tmc2209_frame_read_request(uint8_t out[TMC2209_READ_REQ_LEN],
                                uint8_t slave_addr, uint8_t reg)
{  /* Read requests have only 4 bytes */
    out[0] = TMC2209_SYNC;
    out[1] = (uint8_t)(slave_addr & TMC2209_ADDR_MASK);
    out[2] = (uint8_t)(reg & TMC2209_REG_MASK);
    out[3] = tmc2209_crc8(out, 3);
}

tmc2209_err_t tmc2209_frame_parse_reply(const uint8_t in[TMC2209_REPLY_LEN],
                                        uint8_t expect_reg, uint32_t *out)
{
    if (!in || !out) {
        return TMC2209_ERR_ARG;
    }
    /* CRC first */
    if (in[7] != tmc2209_crc8(in, 7)) {
        return TMC2209_ERR_CRC;
    }

    /* Preamble: the only fields that don't change per reply. Sync is a nibble wide. */
    if ((in[0] & TMC2209_SYNC_MASK) != TMC2209_SYNC || in[1] != TMC2209_MASTER_ADDR) {
        return TMC2209_ERR_PREAMBLE;
    }
    /* A read request for a register must have a reply pointing out the same register. */
    if ((in[2] & TMC2209_REG_MASK) != (expect_reg & TMC2209_REG_MASK)) {
        return TMC2209_ERR_REG;
    }

    /* If all good, return what's important: the read value from the driver */
    *out = ((uint32_t)in[3] << 24) | ((uint32_t)in[4] << 16) |
           ((uint32_t)in[5] << 8)  | (uint32_t)in[6];
    return TMC2209_OK;
}
