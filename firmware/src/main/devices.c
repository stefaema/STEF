#include "devices.h"

#include <string.h>

#include "backends.h"
#include "board.h"
#include "esp_log.h"
#include "tmc2209_err.h"

#define DEVICES_MAX 4  /**< four addresses fit on one wire */

static const char *TAG = "devices";

static tmc2209_t s_devs[DEVICES_MAX];
static size_t    s_count;
static bool      s_ready;

bool devices_init(void)
{
    if (s_ready) {
        return false;
    }

    const board_t *board = board_get();

    esp_err_t err = backends_init(board);
    if (err != ESP_OK) {
        return false;
    }

    const tmc2209_bus_t *bus = backends_bus();
    size_t               n   = board->n_drivers;
    if (n > DEVICES_MAX) {
        ESP_LOGE(TAG, "board declares %u drivers, %d fit on one wire",
                 (unsigned)n, DEVICES_MAX);
        return false;
    }

    for (size_t i = 0; i < n; i++) {
        const board_driver_t *d = &board->drivers[i];

        tmc2209_err_t terr = tmc2209_init(&s_devs[i], d->addr);
        if (terr == TMC2209_OK) {
            terr = tmc2209_attach_bus(&s_devs[i], bus);
        }
        if (terr == TMC2209_OK) {
            terr = tmc2209_attach_lines(&s_devs[i], backends_lines(i));
        }

        if (terr != TMC2209_OK) {
            ESP_LOGE(TAG, "%s: %s", d->name, tmc2209_strerror(terr));
            return false;
        }

        /*
         * No stepgen yet, so a move is refused with NO_BACKEND. Everything
         * that does not emit pulses works regardless, which is the whole
         * argument for backends being separate: a board missing a peripheral
         * is a board that answers for what it has.
         */
        ESP_LOGI(TAG, "%s at address %u, lines 0x%X", d->name, d->addr,
                 backends_lines(i) ? backends_lines(i)->wired : 0u);
    }

    s_count = n;
    s_ready = true;

    return true;
}

bool devices_ready(void)
{
    return s_ready;
}

size_t devices_count(void)
{
    return board_get()->n_drivers;
}

const char *devices_name(size_t i)
{
    const board_t *board = board_get();
    return (i < board->n_drivers) ? board->drivers[i].name : NULL;
}

tmc2209_t *devices_at(size_t i)
{
    return (s_ready && i < s_count) ? &s_devs[i] : NULL;
}

tmc2209_t *devices_by_name(const char *name)
{
    if (!s_ready || name == NULL) {
        return NULL;
    }

    const board_t *board = board_get();
    for (size_t i = 0; i < s_count; i++) {
        if (strcmp(board->drivers[i].name, name) == 0) {
            return &s_devs[i];
        }
    }

    return NULL;
}
