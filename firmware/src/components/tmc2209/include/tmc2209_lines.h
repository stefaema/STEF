/*
 * tmc2209_lines.h: the four control lines, as levels.
 *
 * UART configures the driver; it does not move it. ENN, DIR, STEP and DIAG do,
 * and what each one means is a fact about the part rather than about the board:
 * ENN is active low, DIR selects a phase order that GCONF.shaft then inverts,
 * STEP advances one microstep whose size CHOPCONF.mres sets. Every one of those
 * facts is already in this component, which is why the lines belong here and
 * not in the layer above.
 *
 * Note what is absent, and it is the same absence as in tmc2209_port.h: there
 * is no clock. A backend sets and reads levels. Holding a level for a minimum
 * width, and emitting trains of them at a rate, is timing, and timing is the
 * step generator's problem.
 *
 * The levels here are electrical, at the driver's pin, with no polarity
 * applied. A board that inserts an inverting buffer converts in its backend, so
 * that "ENN high" always means what the datasheet says it means.
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
    TMC2209_LINE_COUNT,
} tmc2209_line_t;

/** Position of @p line in a @ref tmc2209_lines_t::wired mask. */
#define TMC2209_LINE_BIT(line) ((uint8_t)(1u << (unsigned)(line)))

/** Every line this driver has, for a board that wires all four. */
#define TMC2209_LINES_ALL ((uint8_t)((1u << TMC2209_LINE_COUNT) - 1u))

/**
 * @brief What the lines are attached to. One per driver, unlike the shared bus.
 *
 * Both calls report failure as a plain int, as the port does: a backend knows
 * only that a pin moved or did not.
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
