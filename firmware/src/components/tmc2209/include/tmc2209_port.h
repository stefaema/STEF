/*
 * tmc2209_port.h: everything the library needs to communicate.
 *
 * The library's only output is bytes. It is channel agnostic:
 * you can use a ESP32 UART peripheral, a PC serial port, or an array in
 * a unit test. Supply a port and it works anywhere.
 *
 * Note what is absent: there is no clock. Timeouts are passed down as a
 * millisecond count and the port decides how to wait.
 */

#ifndef TMC2209_PORT_H
#define TMC2209_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The port reports failure as a plain int, not tmc2209_err_t: it knows only
   that bytes did or did not move. Classifying that into the component's error
   vocabulary is the caller's job, so this header does not need tmc2209_err.h. */
typedef struct tmc2209_port {
    /* Both return bytes transferred, or negative on failure. A short count is
       a timeout, which the library distinguishes from a hard error. */
    int (*tx)(void *ctx, const uint8_t *buf, size_t len, uint32_t timeout_ms);
    int (*rx)(void *ctx, uint8_t *buf, size_t len, uint32_t timeout_ms);

    void (*purge_rx)(void *ctx);   /* drop stale bytes before a transaction. may be NULL */

    /* Serialize a whole transaction. Both NULL or both set. Unused on target,
       where a single control task owns the bus; kept for the PC-side harness. */
    void (*lock)(void *ctx);
    void (*unlock)(void *ctx);

    /* Every byte on the wire, both directions. NULL to disable, zero cost. */
    void (*trace)(void *ctx, bool outbound, const uint8_t *buf, size_t len);

    void *ctx;

    /* True when transmitted bytes come back on rx, as they do on the
       single-wire half-duplex link. False for a full-duplex backend such as
       the SIL simulator over USB. */
    bool echoes;
} tmc2209_port_t;

#endif /* TMC2209_PORT_H */
