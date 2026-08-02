/*
 * tmc2209_uart_priv.h: the inside of the uart subsystem.
 *
 *
 */

#ifndef TMC2209_UART_PRIV_H
#define TMC2209_UART_PRIV_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tmc2209_err.h"
#include "tmc2209_reg.h"
#include "tmc2209_uart.h"

/* The largest raw transfer tmc2209_uart_send() will carry (therefore the echo buffer) */
#define TMC2209_MAX_TRANSFER 32U

/* In case concurrent access to the port is needed. */
void tmc2209_uart_lock(const tmc2209_uart_t *uart);
void tmc2209_uart_unlock(const tmc2209_uart_t *uart);

/**
 * @brief Reads one register, retrying up to @p uart->retries times.
 *
 * Reads have no side effect, so a retry costs only time. A malformed request
 * is not retried: TMC2209_ERR_REG and TMC2209_ERR_ARG come straight back,
 * because a second identical attempt would fail identically.
 */
tmc2209_err_t tmc2209_uart_read_reg(const tmc2209_uart_t *uart, uint8_t addr,
                                    tmc2209_reg_t reg, uint32_t *out);

/**
 * @brief Writes one register, retrying up to @p uart->retries times.
 *
 * Writes are idempotent at the driver, so a retry is safe, but each attempt
 * that reached the part advanced IFCNT. @p issued is incremented once per
 * attempt so the caller can check the counter against a range rather than an
 * exact delta. It is never reset here: a batch accumulates across calls.
 */
tmc2209_err_t tmc2209_uart_write_reg(const tmc2209_uart_t *uart, uint8_t addr,
                                     tmc2209_reg_t reg, uint32_t value,
                                     unsigned *issued);

#endif /* TMC2209_UART_PRIV_H */
