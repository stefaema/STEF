/**
 * @file backends.h
 * @brief The library's backends, implemented with ESP-IDF.
 *
 * The UART peripheral and the GPIO matrix, with no policy. Which pin, address
 * and driver exist is board.h's, and what a level means is the library's.
 * `test/unit` runs the same library against a mock instead.
 */

#ifndef BACKENDS_H
#define BACKENDS_H

#include <stddef.h>

#include "board.h"
#include "esp_err.h"
#include "tmc2209.h"

/** @brief The address field is two bits wide, so one wire carries four. */
#define BACKENDS_MAX_DRIVERS 4

/**
 * @brief Brings up the UART and every wired GPIO on @p board.
 *
 * Outputs come up in their resting state before they are driven: ENN high, so
 * the power stage is off from the first instruction, and STEP low. This is to
 * avoid a floating pin energising a motor during boot.
 *
 * @retval ESP_OK
 * @retval ESP_ERR_INVALID_STATE  already called
 * @retval ESP_ERR_INVALID_ARG    the table names more drivers than fit
 * @return whatever the UART or GPIO driver returned
 */
esp_err_t backends_init(const board_t *board);

/** @brief The shared UART link, or NULL before backends_init() succeeded. */
const tmc2209_uart_t *backends_uart(void);

/** @brief Lines for driver @p i of the board table, or NULL if out of range. */
const tmc2209_lines_t *backends_lines(size_t i);

/**
 * @brief Claims an RMT channel and a PCNT unit for every driver wiring STEP.
 *
 * Called by backends_init() once the pins are configured, because both
 * peripherals attach to a pad that has to already exist and rest low.
 *
 * @retval ESP_OK
 * @retval ESP_ERR_NOT_FOUND  the chip ran out of RMT channels or PCNT units
 * @return whatever the RMT or PCNT driver returned
 */
esp_err_t backends_stepgen_init(const board_t *board);

/** @brief Pulse source for driver @p i, or NULL if it wires no STEP pin. */
const tmc2209_stepgen_t *backends_stepgen(size_t i);

#endif /* BACKENDS_H */
