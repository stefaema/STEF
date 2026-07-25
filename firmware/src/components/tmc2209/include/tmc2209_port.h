/*
 * tmc2209_port.h — everything the library needs from the outside world.
 *
 * The library's only output is bytes. It never knows whether they reach a
 * TMC2209 through an ESP32 UART peripheral, a PC serial port, or an array in
 * a unit test. Supply a port and it works anywhere.
 *
 * Note what is absent: there is no clock. Timeouts are passed down as a
 * millisecond count and the port decides how to wait. That is what keeps this
 * core free of ESP-IDF and lets the unit tests run instantly instead of
 * sleeping. The consequence is that retries are immediate, with no backoff.
 */

#ifndef TMC2209_PORT_H
#define TMC2209_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    TMC2209_OK = 0,
    TMC2209_ERR_ARG,      /* caller passed something impossible */
    TMC2209_ERR_TIMEOUT,  /* port did not deliver the bytes in time */
    TMC2209_ERR_IO,       /* port failed for its own reasons */
    TMC2209_ERR_ECHO,     /* what came back is not what we sent: collision or jammed line */
    TMC2209_ERR_SYNC,     /* reply sync byte or master address wrong */
    TMC2209_ERR_CRC,
    TMC2209_ERR_REG,      /* reply is for a register we did not ask about */
    TMC2209_ERR_NO_ACK,   /* IFCNT did not advance: the write never landed */
    TMC2209_ERR_ACCESS,   /* read of a write-only register, or write of a read-only one */
    TMC2209_ERR_STALE,    /* shadow is untrusted; reflush before believing it */
} tmc2209_err_t;

const char *tmc2209_strerror(tmc2209_err_t err);

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
