/*
 * mock_tmc2209.h: a fake TMC2209 behind the uart interface.
 *
 * A scripted byte queue would test the framing but make the transaction tests
 * unreadable, because every expectation would be a hand-assembled datagram.
 * So the mock models the device instead: it holds registers, echoes what it
 * receives, answers reads, and counts writes in IFCNT the way the driver
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
#include "tmc2209_frame.h"

#define MOCK_OUT_CAP 64
#define MOCK_LOG_CAP 512

/* Datasheet power-on values. These belong to the device model, not to the
   library: GCONF's depends on OTP bits and CHOPCONF's on the address straps,
   so neither is a property the library may assume. FACTORY_CONF is given a
   non-zero trim precisely because a real part never reads back zero, which is
   what makes "read it, do not seed it" testable. */
#define MOCK_RESET_IOIN         0x21000000U   /* revision byte; the mock picks one, like a part woUld */
#define MOCK_RESET_GCONF        0x00000101U
#define MOCK_RESET_GSTAT        0x00000001U   /* reset flag set at power-on */
#define MOCK_RESET_CHOPCONF     0x10000053U
#define MOCK_RESET_IHOLD_IRUN   0x00071703U
#define MOCK_RESET_TPOWERDOWN   0x00000014U
#define MOCK_RESET_TSTEP        0x000FFFFFU
#define MOCK_RESET_PWMCONF      0xC10D0024U
#define MOCK_RESET_FACTORY_CONF 0x0000001DU

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

    /* Truncation models a link that drops bytes mid-datagram, which is a
       different fault from silence and has to be told apart from it. Each
       keeps only the first n bytes of what it would otherwise deliver. */
    unsigned truncate_echo;
    size_t   echo_keep;
    unsigned truncate_reply;
    size_t   reply_keep;
} mock_dev_t;

/* Zeroes the mock, seeds the power-on register values a real part would show,
   and wires the returned backend to it. Leaves timeout_ms and retries at zero:
   they are the caller's policy, not the device model's. */
void mock_init(mock_dev_t *m, tmc2209_uart_t *uart, uint8_t addr, bool echoes);

uint32_t mock_reg(const mock_dev_t *m, tmc2209_reg_t reg);
void     mock_set_reg(mock_dev_t *m, tmc2209_reg_t reg, uint32_t value);

#endif /* MOCK_TMC2209_H */
