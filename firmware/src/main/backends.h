/**
 * @file backends.h
 * @brief The library's abstract holes, filled with ESP-IDF.
 *
 * `tmc2209_uart_t` wants bytes moved and `tmc2209_lines_t` wants a pin driven.
 * Neither says how, which is what lets the same library run against a mock in
 * `test/unit`. This is the other implementation: UART peripheral, GPIO matrix,
 * and nothing above the level of "the bytes went out" or "the pin is high".
 *
 * Deliberately no policy here. Which pin, which address and which driver
 * exists is board.h's answer; what a level means is the library's. This file
 * only knows how to make a peripheral do it.
 */

#ifndef BACKENDS_H
#define BACKENDS_H

#include <stddef.h>

#include "board.h"
#include "esp_err.h"
#include "tmc2209.h"

/**
 * @brief Brings up the UART and every wired GPIO on @p board.
 *
 * Outputs come up in their resting state before they are driven: ENN high, so
 * the power stage is off from the first instruction, and STEP low. A board
 * that energised a motor because a pin floated during boot would be a board
 * you cannot leave plugged in.
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

#endif /* BACKENDS_H */
