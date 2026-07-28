/**
 * @file dev_main.c
 * @brief The image on the bench board: bring the link up and answer.
 *
 * Not the production entry point. This is what gets flashed onto the test rig
 * so the PC can exercise the RPC layer, then the tmc2209 component, then real
 * drivers, one layer at a time and in that order.
 *
 * There is deliberately nothing here that runs on its own. A dev board that
 * moves a motor at boot is a dev board you cannot leave plugged in, and every
 * capability this image has is supposed to be reachable from the PC anyway.
 */

#include "devices.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"
#include "rpc_dispatch.h"
#include "rpc_link.h"
#include "rpc_methods.h"

static const char *TAG = "stef";

/*
 * The link comes up before the drivers do, deliberately. Construction is the
 * part most likely to fail on a hand-wired board, and a failure that happens
 * before there is anywhere to report it is a failure nobody sees.
 *
 * A construction failure is therefore not fatal here. The link stays up,
 * `sys.state` reports FAULT, and the PC gets told what went wrong. A board
 * that goes silent when its wiring is bad is a board you debug with a
 * multimeter instead of with the tool you already have open.
 */
void app_main(void)
{
    /*
     * The composition root composes. This is the one place that knows both
     * libraries exist, so it is the one place entitled to say which methods
     * this image serves.
     */
    rpc_register(RPC_NS_SYS, rpc_sys_methods, RPC_SYS_COUNT);
    rpc_register(RPC_NS_PASSTHROUGH, rpc_passthrough_methods, RPC_PT_COUNT);
    rpc_register(RPC_NS_RAW, rpc_raw_methods, RPC_RAW_COUNT);

    esp_err_t err = rpc_link_start();
    if (err != ESP_OK) {
        /* No redirect happened, so this goes to the console, which is the only
         * place left. */
        ESP_LOGE(TAG, "rpc link failed to start: %s", esp_err_to_name(err));
        return;
    }

    ESP_LOGI(TAG, "rpc link up, reset reason %d", (int)esp_reset_reason());

    if (!devices_init()) {
        ESP_LOGE(TAG, "device construction failed");
        return;
    }

    ESP_LOGI(TAG, "motion system ready, %u driver(s)", (unsigned)devices_count());
}
