/**
 * @file dev_main.c
 * @brief Registers the RPC namespaces, starts the link and builds the devices.
 */

#include "devices.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"
#include "rpc_dispatch.h"
#include "rpc_link.h"
#include "rpc_methods.h"

static const char *TAG = "stef";

void app_main(void)
{
    /* Register what the firmware can receive as remote procedures */
    rpc_register(RPC_NS_SYS, rpc_sys_methods, RPC_SYS_COUNT);
    rpc_register(RPC_NS_RELAY, rpc_relay_methods, RPC_RELAY_COUNT);
    rpc_register(RPC_NS_RAW, rpc_raw_methods, RPC_RAW_COUNT);

    esp_err_t err = rpc_link_start();
    if (err != ESP_OK) {
        /* No redirect happened, so this goes to the console, which is the only
         * place left. */
        ESP_LOGE(TAG, "rpc link failed to start: %s", esp_err_to_name(err));
        return;
    }

    ESP_LOGI(TAG, "rpc link up, reset reason %d", (int)esp_reset_reason());

    /* Setup the drivers, code-wise */
    if (!devices_init()) {
        ESP_LOGE(TAG, "device construction failed");
        return;
    }

    ESP_LOGI(TAG, "motion system ready, %u driver(s)", (unsigned)devices_count());
}
