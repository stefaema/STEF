/*
 * tmc2209_uart_priv.h: the inside of the uart subsystem.
 *
 * Deliberately not in include/. Every other header here is public because
 * somebody outside has to fill it in or call it. This one exists only because
 * tmc2209.c and tmc2209_uart.c sit on either side of a seam: the device layer
 * reads and writes registers on every call it makes, and the code that puts
 * those on the wire lives in the other file. A caller that wants bytes on the
 * wire without the cache has tmc2209_uart_send(), which is public and says so.
 *
 * What lives below this line is a datagram and the attempts it took. What lives
 * above it is the cache, IFCNT, and what a value means. So nothing here touches
 * a tmc2209_t: the address is passed in rather than reached for, which is what
 * lets these run without a device at all.
 */

#ifndef TMC2209_UART_PRIV_H
#define TMC2209_UART_PRIV_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tmc2209_err.h"
#include "tmc2209_reg.h"
#include "tmc2209_uart.h"

/* The largest raw transfer tmc2209_uart_send() will carry, and therefore the
   stack buffer that verifies its echo. Larger than any single datagram on
   purpose: a passthrough caller may hand over several at once. */
#define TMC2209_MAX_TRANSFER 32U

/* No-ops when the backend supplies no lock, which is the target build. */
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
