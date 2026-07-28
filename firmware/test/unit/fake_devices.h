/* fake_devices.h: what a test installs in place of the board table. */

#ifndef FAKE_DEVICES_H
#define FAKE_DEVICES_H

#include <stddef.h>

#include "devices.h"

#define FAKE_DEVICES_MAX 4

/** Installs @p n devices at indices 0..n-1. Borrowed, so they must outlive it. */
void fake_devices_set(tmc2209_t **devs, const char **names, size_t n);

/** Empties the table, so every index stops resolving. */
void fake_devices_clear(void);

#endif /* FAKE_DEVICES_H */
