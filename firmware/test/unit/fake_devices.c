/*
 * fake_devices.c: the device table, host side.
 *
 * `devices.h` names no ESP-IDF type, so the RPC bridges that look devices up
 * through it compile here unchanged. What they cannot have is the real
 * implementation, which installs a UART and configures GPIOs. This is the
 * other one: devices a test builds itself, wired to whatever backends the test
 * wants to lie about.
 *
 * A link-time seam rather than a function pointer. The bridges call
 * `devices_at()` either way; which `devices_at()` they reach is decided by
 * what got linked, and nothing in the production path pays for the test's
 * existence.
 */

#include "fake_devices.h"

#include <stddef.h>

static tmc2209_t  *s_devs[FAKE_DEVICES_MAX];
static const char *s_names[FAKE_DEVICES_MAX];
static size_t      s_count;

void fake_devices_set(tmc2209_t **devs, const char **names, size_t n)
{
    s_count = (n > FAKE_DEVICES_MAX) ? FAKE_DEVICES_MAX : n;

    for (size_t i = 0; i < s_count; i++) {
        s_devs[i]  = devs ? devs[i] : NULL;
        s_names[i] = names ? names[i] : NULL;
    }
}

void fake_devices_clear(void)
{
    s_count = 0;
}

bool devices_init(void)
{
    return true;
}

bool devices_ready(void)
{
    return s_count > 0;
}

size_t devices_count(void)
{
    return s_count;
}

const char *devices_name(size_t i)
{
    return (i < s_count) ? s_names[i] : NULL;
}

tmc2209_t *devices_at(size_t i)
{
    return (i < s_count) ? s_devs[i] : NULL;
}

tmc2209_t *devices_by_name(const char *name)
{
    (void)name;
    return NULL; /* the bridges address devices by index; nothing calls this */
}
