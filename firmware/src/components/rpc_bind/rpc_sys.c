#include "rpc_methods.h"

#include "devices.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "rpc_api.h"
#include "tmc2209.h"

/* Copies @p src into a fixed field and zeroes the rest of it. The tail matters:
 * the field travels whole, so anything left in it from a previous reply would
 * be both a changing CRC for an unchanged answer and a look at memory the
 * caller was never offered. */
static void set_str(char *dst, size_t cap, const char *src)
{
    size_t n = 0;

    if (src != NULL) {
        while (n + 1U < cap && src[n] != '\0') {
            dst[n] = src[n];
            n++;
        }
    }

    while (n < cap) {
        dst[n] = '\0';
        n++;
    }
}

static rpc_status_t sys_version(const void *args, void *ret)
{
    (void)args;

    rpc_sys_version_ret  *out = ret;
    const esp_app_desc_t *app = esp_app_get_description();

    out->protocol     = RPC_PROTOCOL_VERSION;
    out->reset_reason = (uint8_t)esp_reset_reason();

    set_str(out->project, sizeof(out->project), app ? app->project_name : "");
    set_str(out->version, sizeof(out->version), app ? app->version : "");
    set_str(out->idf, sizeof(out->idf), app ? app->idf_ver : "");

    return RPC_OK;
}

static rpc_status_t sys_state(const void *args, void *ret)
{
    (void)args;

    rpc_sys_state_ret *out   = ret;
    bool               ready = devices_ready();

    out->uptime_ms    = (uint32_t)(esp_timer_get_time() / 1000);
    out->device_count = (uint16_t)devices_count();
    out->mode         = (uint8_t)(ready ? RPC_MODE_IDLE : RPC_MODE_FAULT);
    out->ready        = ready ? 1U : 0U;

    return RPC_OK;
}

static rpc_status_t sys_devices(const void *args, size_t args_len,
                                void *ret, size_t *ret_len)
{
    (void)args;
    (void)args_len;

    rpc_sys_devices_ret *out = ret;

    size_t n = devices_count();
    if (n > RPC_MAX_DEVICES) {
        n = RPC_MAX_DEVICES;
    }

    out->count = (uint32_t)n;

    for (size_t i = 0; i < n; i++) {
        const tmc2209_t *dev  = devices_at(i);
        rpc_dev_info_t  *info = &out->devs[i];

        uint8_t wired = 0;
        for (int line = 0; line < TMC2209_LINE_COUNT; line++) {
            if (dev != NULL && tmc2209_line_is_wired(dev, (tmc2209_line_t)line)) {
                wired |= TMC2209_LINE_BIT(line);
            }
        }

        set_str(info->name, sizeof(info->name), devices_name(i));
        info->addr        = (dev != NULL) ? dev->addr : 0U;
        info->wired       = wired;
        info->has_uart    = (dev != NULL && dev->uart != NULL) ? 1U : 0U;
        info->has_stepgen = (dev != NULL && dev->stepgen != NULL) ? 1U : 0U;
    }

    *ret_len = sizeof(*out) + (n * sizeof(rpc_dev_info_t));
    return RPC_OK;
}

const rpc_method_t rpc_sys_methods[RPC_SYS_COUNT] = {
    [RPC_SYS_VERSION] = RPC_METHOD_GET(sys_version),
    [RPC_SYS_STATE]   = RPC_METHOD_GET(sys_state),
    [RPC_SYS_DEVICES] = RPC_METHOD_VAR_GET(
        sys_devices,
        sizeof(rpc_sys_devices_ret) + (RPC_MAX_DEVICES * sizeof(rpc_dev_info_t))),
};
