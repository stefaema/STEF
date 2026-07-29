/*
 * tmc2209_lines.h: the four control lines, as levels.
 *
 * UART configures the driver; but you also got ENN, DIR, STEP and DIAG lines:
 * ENN enables at active low, DIR selects a phase order that GCONF.shaft then inverts,
 * STEP advances one microstep whose size CHOPCONF.mres sets.
 *
 * The library does not know what the board does with those lines, so it does not drive them.
 * It defers to a backend, which may be a GPIO fd, peripheral, stub, etc.
 *
 * The levels here are electrical, at the driver's pin, with no polarity
 * applied.
 *
 */

#ifndef TMC2209_LINES_H
#define TMC2209_LINES_H

#include <stdbool.h>
#include <stdint.h>

/** @brief The driver's control lines, named as the datasheet names them. */
typedef enum {
    TMC2209_LINE_ENN = 0,  /**< output, active low. High disables the power stage */
    TMC2209_LINE_DIR,      /**< output. Phase order, before GCONF.shaft inverts it */
    TMC2209_LINE_STEP,     /**< output. One microstep per edge */
    TMC2209_LINE_DIAG,     /**< input. Driver error or StallGuard, per GCONF */
    TMC2209_LINE_COUNT,    /**< meta. Amount of lines a driver has */
} tmc2209_line_t;

/** Position of @p line in a @ref tmc2209_lines_t::wired mask. */
#define TMC2209_LINE_BIT(line) ((uint8_t)(1U << (unsigned)(line)))

/** Every line this driver has, for a board that wires all four. */
#define TMC2209_LINES_ALL ((uint8_t)((1U << TMC2209_LINE_COUNT) - 1U))

/**
 * @brief Filled with how a backend reads and writes the four control lines of the driver, through fn pointers.
 *
 * Both calls need to be implemented by the backend, and they are called with the same @p ctx pointer.
 * If a line is not wired on this board, the backend must be able to know and tell the library,
 * in order to make `TMC2209_ERR_UNWIRED` possible as a return value.
 *
 */
typedef struct tmc2209_lines {

    /** @return 0 or 1, the level presently on the pin, or negative on failure.
        An output answers with the level it is driving. */
    int (*read)(void *ctx, tmc2209_line_t line);

    /** @return 0 on success, negative on failure. */
    int (*write)(void *ctx, tmc2209_line_t line, bool level);

    void *ctx;

    /** One bit per @ref tmc2209_line_t, via TMC2209_LINE_BIT. A line left out
        is one this board does not connect, and every call naming it is
        refused rather than silently moving some other pin. */
    uint8_t wired;
} tmc2209_lines_t;

/** @brief True for a line the driver reads. DIAG is the one it does not. */
bool tmc2209_line_is_output(tmc2209_line_t line);

#endif /* TMC2209_LINES_H */
