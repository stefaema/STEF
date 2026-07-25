/*
 * mock_tmc2209.h — a fake TMC2209 behind the port interface.
 *
 * A scripted byte queue would test the framing but make the transaction tests
 * unreadable, because every expectation would be a hand-assembled datagram.
 * So the mock models the device instead: it holds registers, echoes what it
 * receives, answers reads, and counts writes in IFCNT the way the silicon
 * does. Tests then say "the register should now hold X" rather than "byte 4
 * should be 0x17".
 *
 * The fault flags are the point of the whole exercise. Each one is consumed
 * by the next transaction, so a test can inject exactly one corrupted CRC and
 * assert that the retry path recovers.
 */

#ifndef MOCK_TMC2209_H
#define MOCK_TMC2209_H

#include "tmc2209.h"

#define MOCK_OUT_CAP 64
#define MOCK_LOG_CAP 512

typedef struct {
    uint32_t regs[128];       /* indexed by register address */
    uint8_t  ifcnt;
    uint8_t  addr;            /* the slave address this mock answers to */
    bool     echoes;

    uint8_t  out[MOCK_OUT_CAP];   /* bytes waiting to be read back */
    size_t   out_len, out_pos;

    uint8_t  tx_log[MOCK_LOG_CAP];  /* every byte the library transmitted */
    size_t   tx_len;

    unsigned writes_seen;
    unsigned reads_seen;
    unsigned purges;

    /* Fault injection. Each is decremented and applied once. */
    unsigned fail_crc;        /* corrupt the CRC of the next reply */
    unsigned drop_reply;      /* answer a read with silence */
    unsigned corrupt_echo;    /* flip a bit in the echo */
    unsigned wrong_reg;       /* answer with a different register id */
    unsigned freeze_ifcnt;    /* accept a write without counting it */
} mock_dev_t;

/* Zeroes the mock, sets IOIN.version to 0x21 so tmc2209_begin() passes, and
   wires the returned port to it. */
void mock_init(mock_dev_t *m, tmc2209_port_t *port, uint8_t addr, bool echoes);

uint32_t mock_reg(const mock_dev_t *m, tmc2209_reg_t reg);
void     mock_set_reg(mock_dev_t *m, tmc2209_reg_t reg, uint32_t value);

#endif /* MOCK_TMC2209_H */
