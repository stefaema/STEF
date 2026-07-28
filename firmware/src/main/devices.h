/**
 * @file devices.h
 * @brief Every driver the board declares, constructed and attached, at boot.
 *
 * There is no mode to enter before a driver exists. Construction is
 * unconditional and happens once, so the state a diagnostic script wants and
 * the state a scan starts from are the same state, reached by the same code.
 * The alternative, building devices when someone asks for them, means the
 * production path and the tested path are different paths.
 *
 * What varies between boards is therefore never *whether* a device exists, only
 * what it has. A driver with no stepgen answers NO_BACKEND to a move; a line
 * the board leaves out answers UNWIRED. Both are the library's own answers, per
 * call, with a reason, which is why nothing here needs a build flag.
 *
 * Names, not indices. A device is addressed the way the PC addresses it, and
 * the mapping to a strap address lives in board.h.
 *
 * This header names no ESP-IDF type, so the RPC bridges that look devices up
 * through it stay host-compilable. `test/unit` links a fake implementation.
 */

#ifndef DEVICES_H
#define DEVICES_H

#include <stdbool.h>
#include <stddef.h>

#include "tmc2209.h"

/**
 * @brief Constructs every driver in the board table and attaches its backends.
 *
 * Returns with each driver initialised, holding no configuration, and standing
 * still. Nothing is written to the silicon: the drivers may not even be
 * powered. `raw.bringup` is what makes a driver hold a configuration.
 *
 * All or nothing. A partial set would be a board that answers for some devices
 * and not others with no way to tell which.
 *
 * Reports only whether it worked. What went wrong is logged where it happened,
 * naming the device and the library's own reason, which is more use than a
 * code at the call site.
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
