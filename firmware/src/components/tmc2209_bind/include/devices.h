/**
 * @file devices.h
 * @brief Every driver the board declares, constructed and attached at boot.
 *
 * Construction is unconditional and happens once, so diagnostics and a scan
 * start from the same state through the same code.
 *
 * Boards differ only in what a device has. A driver with no stepgen answers
 * NO_BACKEND to a move and an unwired line answers UNWIRED, so nothing here
 * needs a build flag.
 *
 * A device is addressed by its index in the board table. The mapping to a
 * strap address lives in board.h.
 *
 * Names no ESP-IDF type, so the RPC bridges stay host-compilable. `test/unit`
 * links a fake.
 */

#ifndef DEVICES_H
#define DEVICES_H

#include <stdbool.h>
#include <stddef.h>

#include "tmc2209.h"

/**
 * @brief Constructs every driver in the board table and attaches its backends.
 *
 * Returns with each driver initialised, unconfigured and standing still.
 * Nothing is written to the drivers, which may not even be powered.
 * `raw.bringup` configures them.
 *
 * All or nothing, to avoid a board that answers for some devices and not
 * others. Failures are logged where they happen, naming the device and the
 * library's reason.
 *
 * @return false if already called, or if any backend or device refused
 */
bool devices_init(void);

/** @brief True once devices_init() has succeeded. */
bool devices_ready(void);

/** @brief How many drivers this board declares. Valid before init. */
size_t devices_count(void);

/** @brief Name of driver @p i, or NULL if out of range. Valid before init. */
const char *devices_name(size_t i);

/** @brief Driver @p i, or NULL if out of range or not yet constructed. */
tmc2209_t *devices_at(size_t i);

/** @brief The driver the PC calls @p name, or NULL if this board has no such. */
tmc2209_t *devices_by_name(const char *name);

#endif /* DEVICES_H */
