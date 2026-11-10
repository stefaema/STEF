/**
 * @file board.h
 * @brief Which pins, which addresses, which drivers exist.
 *
 * The library takes backends, and a backend needs GPIO numbers, a UART and a
 * strap address. They live here only, so the layers above name a device by
 * index and a line by role, and the same firmware serves a one-driver bench
 * board or the three-motor carrier.
 *
 * The numbers come from Kconfig, so a board wired differently is
 * `idf.py menuconfig`.
 */

#ifndef BOARD_H
#define BOARD_H

#include <stddef.h>
#include <stdint.h>

/** A pin this board does not connect. The line is then refused, per device. */
#define BOARD_PIN_NONE (-1)

/** @brief One TMC2209 and how it is reached. */
typedef struct {
    const char *name;  /**< what the PC calls it, e.g. "capstan" */
    uint8_t     addr;  /**< 0..3, set by the MS1/MS2 straps */
    int         enn;   /**< GPIO, or BOARD_PIN_NONE */
    int         dir;
    int         step;
    int         diag;
} board_driver_t;

/** @brief The wire they share, and everything on it. */
typedef struct {
    int      uart_num;  /**< UART peripheral carrying the single-wire link */
    int      uart_tx;   /**< to PDN_UART through the series resistor */
    int      uart_rx;   /**< to PDN_UART directly. Sees our own bytes echoed */
    uint32_t baud;
    uint32_t timeout_ms;  /**< per port call, before the bus gives up */
    uint8_t  retries;     /**< further attempts after a timeout or a bad CRC */

    const board_driver_t *drivers;
    size_t                n_drivers;
} board_t;

/** @brief The board this image was built for. Never NULL. */
const board_t *board_get(void);

#endif /* BOARD_H */
