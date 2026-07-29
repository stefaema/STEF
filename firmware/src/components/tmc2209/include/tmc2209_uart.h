/*
 * tmc2209_uart.h: the single-wire link, and the policy for driving it.
 *
 * The library's only output is bytes. It is channel agnostic: an ESP32 UART
 * peripheral, a PC serial port, or an array in a unit test all work, as long as
 * something moves the bytes.
 *
 * Note what is absent: there is no clock. Timeouts are a millisecond count and
 * the backend decides how to wait.
 *
 * The struct holds two kinds of thing, and it is worth knowing which is which.
 * The calls, the ctx and `echoes` are the backend's: an implementor supplies
 * them and they describe what this channel is. `timeout_ms` and `retries` are
 * policy the library applies on top, and no backend is consulted about them.
 * They live here because they are properties of the wire rather than of any one
 * driver on it, so the four drivers sharing a link share its patience too.
 */

#ifndef TMC2209_UART_H
#define TMC2209_UART_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Failure is a plain int, not tmc2209_err_t: a backend knows only that bytes
   did or did not move. Classifying that into the component's error vocabulary
   is the caller's job, so this header does not need tmc2209_err.h. */
typedef struct tmc2209_uart {
    /* Both return bytes transferred, or negative on failure. A short count is
       a timeout, which the library distinguishes from a hard error. */
    int (*tx)(void *ctx, const uint8_t *buf, size_t len, uint32_t timeout_ms);
    int (*rx)(void *ctx, uint8_t *buf, size_t len, uint32_t timeout_ms);

    void (*purge_rx)(void *ctx);   /* drop stale bytes before a transaction. may be NULL */

    /* Serialize a whole transaction. Both NULL or both set. Unused on target,
       where a single control task owns the link; kept for the PC-side harness. */
    void (*lock)(void *ctx);
    void (*unlock)(void *ctx);

    /* Every byte on the wire, both directions. NULL to disable, zero cost. */
    void (*trace)(void *ctx, bool outbound, const uint8_t *buf, size_t len);

    void *ctx;

    /* True when transmitted bytes come back on rx, as they do on the
       single-wire half-duplex link. False for a full-duplex backend such as
       the SIL simulator over USB. */
    bool echoes;

    /* ── Library policy, not backend ──────────────────────────────────────── */

    uint32_t timeout_ms;   /**< per call into tx or rx */
    uint8_t  retries;      /**< additional attempts after a CRC or timeout failure */
} tmc2209_uart_t;

#endif /* TMC2209_UART_H */
