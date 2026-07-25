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
    out[0] = TMC2209_SYNC;
    out[1] = (uint8_t)(slave_addr & 0x03u);
    out[2] = (uint8_t)(reg | 0x80u);          /* bit 7 marks the datagram a write */
    out[3] = (uint8_t)(value >> 24);
    out[4] = (uint8_t)(value >> 16);
    out[5] = (uint8_t)(value >> 8);
    out[6] = (uint8_t)(value);
    out[7] = tmc2209_crc8(out, 7);
}

void tmc2209_frame_read_request(uint8_t out[TMC2209_READ_REQ_LEN],
                                uint8_t slave_addr, uint8_t reg)
{
    out[0] = TMC2209_SYNC;
    out[1] = (uint8_t)(slave_addr & 0x03u);
    out[2] = (uint8_t)(reg & 0x7Fu);
    out[3] = tmc2209_crc8(out, 3);
}

tmc2209_err_t tmc2209_frame_parse_reply(const uint8_t in[TMC2209_REPLY_LEN],
                                        uint8_t expect_reg, uint32_t *out)
{
    if (!in || !out) {
        return TMC2209_ERR_ARG;
    }
    if (in[0] != TMC2209_SYNC || in[1] != TMC2209_MASTER_ADDR) {
        return TMC2209_ERR_SYNC;
    }
    /* Check the register before the CRC. A reply for the wrong register is a
       different failure from a corrupted one: it means a second driver
       answered, which retrying will not fix. */
    if ((in[2] & 0x7Fu) != (expect_reg & 0x7Fu)) {
        return TMC2209_ERR_REG;
    }
    if (in[7] != tmc2209_crc8(in, 7)) {
        return TMC2209_ERR_CRC;
    }
    *out = ((uint32_t)in[3] << 24) | ((uint32_t)in[4] << 16) |
           ((uint32_t)in[5] << 8)  | (uint32_t)in[6];
    return TMC2209_OK;
}

const char *tmc2209_strerror(tmc2209_err_t err)
{
    switch (err) {
    case TMC2209_OK:           return "ok";
    case TMC2209_ERR_ARG:      return "bad argument";
    case TMC2209_ERR_TIMEOUT:  return "timeout";
    case TMC2209_ERR_IO:       return "port I/O failure";
    case TMC2209_ERR_ECHO:     return "echo mismatch (bus collision?)";
    case TMC2209_ERR_SYNC:     return "bad sync or master address";
    case TMC2209_ERR_CRC:      return "CRC mismatch";
    case TMC2209_ERR_REG:      return "reply for unexpected register";
    case TMC2209_ERR_NO_ACK:   return "IFCNT did not advance";
    case TMC2209_ERR_ACCESS:   return "register access violation";
    case TMC2209_ERR_STALE:    return "shadow untrusted";
    case TMC2209_ERR_VERSION:  return "unexpected IOIN.version";
    }
    return "unknown";
}
