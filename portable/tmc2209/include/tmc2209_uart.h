/*
 * tmc2209_uart.h: the single-wire link handling TMC2209 smart configuration.
 *
 * The library's only output is bytes. It is channel agnostic: an ESP32 UART
 * peripheral, a PC serial port, or an array in a unit test all work, as long as
 * something moves the bytes.
 *
 * The calls, ctx and `echoes` are the backend's. `timeout_ms` and `retries` are
 * library policy, kept here because they belong to the wire, so the drivers
 * sharing a link share them too.
 */

#ifndef TMC2209_UART_H
#define TMC2209_UART_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Failure is a plain int, since a backend only knows whether bytes moved.
   Mapping that to tmc2209_err_t is the caller's job. */
typedef struct tmc2209_uart {
    /* Both return bytes transferred, or negative on failure. A short count is
       a timeout, which the library distinguishes from a hard error. */
    int (*tx)(void *ctx, const uint8_t *buf, size_t len, uint32_t timeout_ms);
    int (*rx)(void *ctx, uint8_t *buf, size_t len, uint32_t timeout_ms);

    void (*purge_rx)(void *ctx);   /* drop stale bytes before a transaction. may be NULL */

    /* Serialize a whole transaction. Both NULL or both set. Unneeded where a
       single control task owns the link. */
    void (*lock)(void *ctx);
    void (*unlock)(void *ctx);

    /* Every byte on the wire, both directions. NULL to disable, zero cost. */
    void (*trace)(void *ctx, bool outbound, const uint8_t *buf, size_t len);

    void *ctx;

    /* True when transmitted bytes come back on rx, as they do on the
       single-wire half-duplex link. False for a full-duplex backend such as
       the SIL simulator over USB. */
    bool echoes;

    /* ── Library policy ───────────────────────────────────────────────────── */

    uint32_t timeout_ms;   /**< per call into tx or rx */
    uint8_t  retries;      /**< additional attempts after a CRC or timeout failure */
} tmc2209_uart_t;

#endif /* TMC2209_UART_H */
