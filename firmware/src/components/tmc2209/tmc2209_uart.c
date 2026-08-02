/*
 * tmc2209_uart.c: bytes on the wire, and nothing about what they mean.
 *
 * The backend moves bytes and reports whether they moved. What it cannot know
 * is what a transaction is: that a read request is answered by a reply and not
 * by our own echo, that the echo has to be consumed before the reply can be
 * read at all, and that a CRC failure is worth one more attempt while a reply
 * about the wrong register is not.
 *
 */

#include "tmc2209.h"
#include "tmc2209_frame.h"
#include "tmc2209_uart_priv.h"

#include <string.h>

/* ── Backend plumbing ───────────────────────────────────────────────────── */

static void trace(const tmc2209_uart_t *uart, bool out, const uint8_t *b, size_t n)
{
    if (uart->trace) {
        uart->trace(uart->ctx, out, b, n);
    }
}

void tmc2209_uart_lock(const tmc2209_uart_t *uart)
{
    if (uart->lock) {
        uart->lock(uart->ctx);
    }
}

void tmc2209_uart_unlock(const tmc2209_uart_t *uart)
{
    if (uart->unlock) {
        uart->unlock(uart->ctx);
    }
}

static void uart_purge(const tmc2209_uart_t *uart)
{
    if (uart->purge_rx) {
        uart->purge_rx(uart->ctx);
    }
}

static tmc2209_err_t uart_tx(const tmc2209_uart_t *uart, const uint8_t *buf, size_t len)
{
    int n = uart->tx(uart->ctx, buf, len, uart->timeout_ms);
    trace(uart, true, buf, len);
    if (n < 0) {
        return TMC2209_ERR_IO;
    }
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_TX_TIMEOUT;
}

/* @p got reports how many bytes actually arrived. */
static tmc2209_err_t uart_rx(const tmc2209_uart_t *uart, uint8_t *buf, size_t len,
                             size_t *got)
{
    if (got) {
        *got = 0;
    }
    int n = uart->rx(uart->ctx, buf, len, uart->timeout_ms);
    if (n < 0) {
        return TMC2209_ERR_IO;
    }
    if (got) {
        *got = (size_t)n;
    }
    trace(uart, false, buf, (size_t)n);
    return ((size_t)n == len) ? TMC2209_OK : TMC2209_ERR_RX_TIMEOUT;
}

/* Echo is evidence, not litter. Short and altered are both "not what we sent". */
static tmc2209_err_t verify_echo(const tmc2209_uart_t *uart,
                                 const uint8_t *sent, size_t len)
{
    if (!uart->echoes) {
        return TMC2209_OK;
    }
    if (len > TMC2209_MAX_TRANSFER) {
        return TMC2209_ERR_ARG;
    }
    uint8_t echo[TMC2209_MAX_TRANSFER];
    tmc2209_err_t err = uart_rx(uart, echo, len, NULL);
    if (err == TMC2209_ERR_RX_TIMEOUT) {
        return TMC2209_ERR_ECHO;
    }
    if (err != TMC2209_OK) {
        return err;
    }
    return (memcmp(echo, sent, len) == 0) ? TMC2209_OK : TMC2209_ERR_ECHO;
}

/* ── Single transactions, one attempt each ──────────────────────────────── */

static tmc2209_err_t read_once(const tmc2209_uart_t *uart, uint8_t addr,
                               tmc2209_reg_t reg, uint32_t *out)
{
    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, addr, (uint8_t)reg);

    uart_purge(uart);

    tmc2209_err_t err = uart_tx(uart, req, sizeof req);
    if (err != TMC2209_OK) {
        return err;
    }
    err = verify_echo(uart, req, sizeof req);
    if (err != TMC2209_OK) {
        return err;
    }

    uint8_t reply[TMC2209_REPLY_LEN];
    err = uart_rx(uart, reply, sizeof reply, NULL);
    if (err != TMC2209_OK) {
        return err;
    }
    return tmc2209_frame_parse_reply(reply, (uint8_t)reg, out);
}

static tmc2209_err_t write_once(const tmc2209_uart_t *uart, uint8_t addr,
                                tmc2209_reg_t reg, uint32_t value)
{
    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, addr, (uint8_t)reg, value);

    uart_purge(uart);

    tmc2209_err_t err = uart_tx(uart, dg, sizeof dg);
    if (err != TMC2209_OK) {
        return err;
    }
    return verify_echo(uart, dg, sizeof dg);
}

/* ── Single transactions, multiple attempts ──────────────────────────────── */

tmc2209_err_t tmc2209_uart_read_reg(const tmc2209_uart_t *uart, uint8_t addr,
                                    tmc2209_reg_t reg, uint32_t *out)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= uart->retries; attempt++) {
        err = read_once(uart, addr, reg, out);
        if (err == TMC2209_OK) {
            return TMC2209_OK;
        }
        /* Draining what is already buffered needs purge_rx, which the backend
           need not supply, so a retry can read the same bytes back. */
        if (err == TMC2209_ERR_REG || err == TMC2209_ERR_ARG) {
            return err;
        }
    }
    return err;
}

tmc2209_err_t tmc2209_uart_write_reg(const tmc2209_uart_t *uart, uint8_t addr,
                                     tmc2209_reg_t reg, uint32_t value,
                                     unsigned *issued)
{
    tmc2209_err_t err = TMC2209_ERR_IO;
    for (unsigned attempt = 0; attempt <= uart->retries; attempt++) {
        (*issued)++;
        err = write_once(uart, addr, reg, value);
        if (err == TMC2209_OK) {
            return TMC2209_OK;
        }
    }
    return err;
}

/* ── Public API ─────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_attach_uart(tmc2209_t *dev, const tmc2209_uart_t *uart)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    /* Half a backend is not a backend */
    if (uart && (!uart->tx || !uart->rx)) {
        return TMC2209_ERR_ARG;
    }
    dev->uart = uart;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_uart_send(const tmc2209_uart_t *uart,
                                const uint8_t *tx, size_t tx_len,
                                uint8_t *rx, size_t rx_len, size_t *rx_got)
{
    if (rx_got) {
        *rx_got = 0;
    }
    if (!uart || !tx || tx_len == 0 || tx_len > TMC2209_MAX_TRANSFER) {
        return TMC2209_ERR_ARG;
    }
    if (rx_len > 0 && !rx) {
        return TMC2209_ERR_ARG;
    }

    tmc2209_uart_lock(uart);
    uart_purge(uart);

    tmc2209_err_t err = uart_tx(uart, tx, tx_len);
    if (err == TMC2209_OK) {
        err = verify_echo(uart, tx, tx_len);
    }

    /* The reply is collected even after a bad echo.*/
    if ((err == TMC2209_OK || err == TMC2209_ERR_ECHO) && rx_len > 0) {
        size_t got = 0;
        tmc2209_err_t reply_err = uart_rx(uart, rx, rx_len, &got);
        if (rx_got) {
            *rx_got = got;
        }
        if (err == TMC2209_OK) {
            err = reply_err;
        }
    }

    tmc2209_uart_unlock(uart);
    return err;
}
