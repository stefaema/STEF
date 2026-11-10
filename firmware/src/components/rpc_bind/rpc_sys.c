#include "rpc_methods.h"

#include "devices.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "fw_api.h"
#include "rpc_trip.h"
#include "tmc2209.h"

/* clang-format off */
/* NOLINTBEGIN(readability-redundant-casting) */
static_assert((int)RPC_RESET_UNKNOWN    == (int)ESP_RST_UNKNOWN,    "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_POWERON    == (int)ESP_RST_POWERON,    "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_EXT        == (int)ESP_RST_EXT,        "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_SW         == (int)ESP_RST_SW,         "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_PANIC      == (int)ESP_RST_PANIC,      "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_INT_WDT    == (int)ESP_RST_INT_WDT,    "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_TASK_WDT   == (int)ESP_RST_TASK_WDT,   "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_WDT        == (int)ESP_RST_WDT,        "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_DEEPSLEEP  == (int)ESP_RST_DEEPSLEEP,  "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_BROWNOUT   == (int)ESP_RST_BROWNOUT,   "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_SDIO       == (int)ESP_RST_SDIO,       "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_USB        == (int)ESP_RST_USB,        "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_JTAG       == (int)ESP_RST_JTAG,       "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_EFUSE      == (int)ESP_RST_EFUSE,      "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_PWR_GLITCH == (int)ESP_RST_PWR_GLITCH, "rpc_reset_t drifted from ESP-IDF");
static_assert((int)RPC_RESET_CPU_LOCKUP == (int)ESP_RST_CPU_LOCKUP, "rpc_reset_t drifted from ESP-IDF");
/* NOLINTEND(readability-redundant-casting) */
/* clang-format on */

/* Copies @p src into a fixed field and zeroes the rest, to avoid leftovers from
 * a previous reply changing the CRC or exposing memory. */
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

    out->reset_reason = (uint8_t)esp_reset_reason();

    /* From the header both ends compile, to avoid comparing a build label someone
     * may rename. */
    set_str(out->version, sizeof(out->version), FW_API_VERSION);
    set_str(out->backend, sizeof(out->backend), FW_API_BACKEND);

    set_str(out->idf, sizeof(out->idf), app ? app->idf_ver : "");

    return RPC_OK;
}

static rpc_status_t sys_state(const void *args, void *ret)
{
    (void)args;

    rpc_sys_state_ret *out    = ret;
    rpc_trip_reason_t  reason = rpc_trip_reason();

    rpc_mode_t mode = RPC_MODE_IDLE;
    if (!devices_ready()) {
        mode = RPC_MODE_FAULT;
    } else if (reason != RPC_TRIP_NONE) {
        mode = RPC_MODE_TRIPPED;
    }

    out->uptime_ms    = (uint32_t)(esp_timer_get_time() / 1000);
    out->device_count = (uint16_t)devices_count();
    out->mode         = (uint8_t)mode;
    out->trip_reason  = (uint8_t)reason;
    out->trip_detail  = rpc_trip_detail();

    return RPC_OK;
}

static rpc_status_t sys_devices(const void *args, size_t args_len, void *ret, size_t *ret_len)
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

static rpc_status_t sys_trip(const void *args, void *ret)
{
    const rpc_sys_trip_args *in = args;
    (void)ret;

    rpc_trip(RPC_TRIP_REQUESTED, in->detail, in->immediate != 0U);
    return RPC_OK;
}

static rpc_status_t sys_untrip(const void *args, void *ret)
{
    (void)args;

    rpc_sys_untrip_ret *out = ret;

    out->reason = (uint8_t)rpc_trip_reason();
    out->detail = rpc_trip_detail();

    return rpc_untrip() ? RPC_OK : RPC_BUSY;
}

const rpc_method_t rpc_sys_methods[RPC_SYS_COUNT] = {
    [RPC_SYS_VERSION] = RPC_METHOD_GET(sys_version),
    [RPC_SYS_STATE]   = RPC_METHOD_GET(sys_state),
    [RPC_SYS_DEVICES] = RPC_METHOD_VAR_GET(
        sys_devices, sizeof(rpc_sys_devices_ret) + (RPC_MAX_DEVICES * sizeof(rpc_dev_info_t))),
    [RPC_SYS_TRIP]   = RPC_METHOD_ACK(sys_trip),
    [RPC_SYS_UNTRIP] = RPC_METHOD_GET(sys_untrip),
};
