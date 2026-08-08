/*
 * tmc2209_lines.h: the four control lines, as levels.
 *
 * UART configures the driver; but you also got ENN, DIR, STEP and DIAG lines:
 * ENN enables at active low, DIR selects a phase order that GCONF.shaft then inverts,
 * STEP advances one microstep whose size CHOPCONF.mres sets. DIAG is an input that signals
 * driver error or StallGuard, depending on GCONF settings.
 *
 * The library does not know what the board does with those lines, so it does not drive them.
 * It defers to a backend, which may be a GPIO fd, peripheral, stub, etc.
 *
 * The levels at the backend level and at this file are electrical, what the driver's
 * pin sees, with no polarity applied.
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
 * @brief The level on a pin, electrical and with no polarity applied.
 *
 * A bool would imply a default direction that only the wiring knows; these two
 * names say exactly what the field is.
 */
typedef enum {
    TMC2209_LOW  = 0,
    TMC2209_HIGH = 1,
} tmc2209_level_t;

/** @brief A @ref tmc2209_line_t narrowed to a byte. */
typedef uint8_t tmc2209_line_id_t;

/** @brief One bit per @ref tmc2209_line_t, via @ref TMC2209_LINE_BIT. */
typedef uint8_t tmc2209_line_mask_t;

/** @brief A @ref tmc2209_level_t narrowed to a byte, for a field on a wire. */
typedef uint8_t tmc2209_level_id_t;

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
    tmc2209_line_mask_t wired;
} tmc2209_lines_t;

/** @brief True for a line the driver reads. DIAG is the one it does not. */
bool tmc2209_line_is_output(tmc2209_line_t line);

#endif /* TMC2209_LINES_H */
