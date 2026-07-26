#include "mock_tmc2209.h"

#include <string.h>

static void push(mock_dev_t *m, const uint8_t *b, size_t n)
{
    if (m->out_len + n > MOCK_OUT_CAP) {
        return;
    }
    memcpy(&m->out[m->out_len], b, n);
    m->out_len += n;
}

/* The device answers a read by building a reply datagram. Faults are applied
   after the frame is well-formed, so each one corrupts exactly one thing. */
static void answer_read(mock_dev_t *m, uint8_t reg)
{
    if (m->drop_reply) {
        m->drop_reply--;
        return;
    }

    uint8_t served = reg;
    if (m->wrong_reg) {
        m->wrong_reg--;
        served = (uint8_t)((reg + 1) & 0x7Fu);
    }

    uint32_t v = m->regs[reg & 0x7Fu];
    uint8_t reply[TMC2209_REPLY_LEN] = {
        TMC2209_SYNC, TMC2209_MASTER_ADDR, served,
        (uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v, 0
    };
    reply[7] = tmc2209_crc8(reply, 7);

    if (m->fail_crc) {
        m->fail_crc--;
        reply[7] ^= 0xFFu;
    }
    push(m, reply, sizeof reply);
}

static int mock_tx(void *ctx, const uint8_t *buf, size_t len, uint32_t timeout_ms)
{
    (void)timeout_ms;
    mock_dev_t *m = (mock_dev_t *)ctx;

    if (m->tx_len + len <= MOCK_LOG_CAP) {
        memcpy(&m->tx_log[m->tx_len], buf, len);
        m->tx_len += len;
    }

    if (m->echoes) {
        uint8_t echo[MOCK_OUT_CAP];
        size_t n = (len > MOCK_OUT_CAP) ? MOCK_OUT_CAP : len;
        memcpy(echo, buf, n);
        if (m->corrupt_echo) {
            m->corrupt_echo--;
            echo[n - 1] ^= 0x01u;
        }
        push(m, echo, n);
    }

    /* Only frames addressed to us get acted on, which is what makes the
       shared-bus addressing testable. */
    if (len >= 3 && buf[0] == TMC2209_SYNC && buf[1] == m->addr) {
        if (len == TMC2209_WRITE_LEN && (buf[2] & 0x80u)) {
            uint8_t  reg = (uint8_t)(buf[2] & 0x7Fu);
            uint32_t val = ((uint32_t)buf[3] << 24) | ((uint32_t)buf[4] << 16) |
                           ((uint32_t)buf[5] << 8)  | (uint32_t)buf[6];
            if (reg == TMC2209_GSTAT) {
                m->regs[reg] &= ~val;   /* write 1 to clear, not store */
            } else {
                m->regs[reg] = val;
            }
            m->writes_seen++;
            if (m->freeze_ifcnt) {
                m->freeze_ifcnt--;
            } else {
                m->ifcnt++;
            }
            m->regs[TMC2209_IFCNT] = m->ifcnt;
        } else if (len == TMC2209_READ_REQ_LEN) {
            m->reads_seen++;
            m->regs[TMC2209_IFCNT] = m->ifcnt;
            answer_read(m, (uint8_t)(buf[2] & 0x7Fu));
        }
    }
    return (int)len;
}

static int mock_rx(void *ctx, uint8_t *buf, size_t len, uint32_t timeout_ms)
{
    (void)timeout_ms;
    mock_dev_t *m = (mock_dev_t *)ctx;

    size_t avail = m->out_len - m->out_pos;
    size_t n     = (len < avail) ? len : avail;   /* a short read is a timeout */
    memcpy(buf, &m->out[m->out_pos], n);
    m->out_pos += n;
    return (int)n;
}

static void mock_purge(void *ctx)
{
    mock_dev_t *m = (mock_dev_t *)ctx;
    m->purges++;
    m->out_len = 0;
    m->out_pos = 0;
}

void mock_init(mock_dev_t *m, tmc2209_port_t *port, uint8_t addr, bool echoes)
{
    memset(m, 0, sizeof *m);
    m->addr   = addr;
    m->echoes = echoes;

    /* Power-on state the library will find. The reset values live here, in the
       device model, rather than in the register table: they describe what a
       chip holds before anyone configures it, which is the mock's business and
       not something the library should carry defaults for. */
    m->regs[TMC2209_IOIN]         = (uint32_t)TMC2209_IOIN_VERSION << 24;
    m->regs[TMC2209_GCONF]        = MOCK_RESET_GCONF;
    m->regs[TMC2209_GSTAT]        = MOCK_RESET_GSTAT;
    m->regs[TMC2209_CHOPCONF]     = MOCK_RESET_CHOPCONF;
    m->regs[TMC2209_IHOLD_IRUN]   = MOCK_RESET_IHOLD_IRUN;
    m->regs[TMC2209_TPOWERDOWN]   = MOCK_RESET_TPOWERDOWN;
    m->regs[TMC2209_TSTEP]        = MOCK_RESET_TSTEP;
    m->regs[TMC2209_PWMCONF]      = MOCK_RESET_PWMCONF;
    m->regs[TMC2209_FACTORY_CONF] = MOCK_RESET_FACTORY_CONF;

    memset(port, 0, sizeof *port);
    port->tx       = mock_tx;
    port->rx       = mock_rx;
    port->purge_rx = mock_purge;
    port->ctx      = m;
    port->echoes   = echoes;
}

uint32_t mock_reg(const mock_dev_t *m, tmc2209_reg_t reg)
{
    return m->regs[(uint8_t)reg & 0x7Fu];
}

void mock_set_reg(mock_dev_t *m, tmc2209_reg_t reg, uint32_t value)
{
    m->regs[(uint8_t)reg & 0x7Fu] = value;
}
