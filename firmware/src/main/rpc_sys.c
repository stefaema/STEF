#include "rpc_methods.h"

#include "devices.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "rpc_api.h"
#include "rpc_wire.h"
#include "tmc2209.h"
#include "watchdog.h"

/*
 * The one method that must answer on a link whose version has not been agreed
 * yet. So the protocol version goes first and is fixed width: a PC built
 * against a different protocol can read that field, decide it does not
 * understand the rest, and say so, which is the whole point of asking.
 *
 * Everything after it is descriptive. The reset reason is here because the
 * question a stale link raises first is "did the board reboot", and answering
 * it costs one word.
 */
static rpc_status_t sys_version(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)args;

    const esp_app_desc_t *app = esp_app_get_description();

    rpc_w_u16(ret, RPC_PROTOCOL_VERSION);
    rpc_w_str(ret, app ? app->project_name : "");
    rpc_w_str(ret, app ? app->version : "");
    rpc_w_str(ret, app ? app->idf_ver : "");
    rpc_w_u8(ret, (uint8_t)esp_reset_reason());

    return RPC_OK;
}

/*
 * Reported, never set. The PC does not announce that it is about to run
 * diagnostics; it asks what is happening and is refused per call if the answer
 * makes the call unsafe. So this is the whole of the mode system from the
 * outside: one question, no state to keep in sync across a link that can drop.
 */
static rpc_status_t sys_state(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)args;

    bool ready = devices_ready();

    rpc_w_u8(ret, (uint8_t)(ready ? RPC_MODE_IDLE : RPC_MODE_FAULT));
    rpc_w_bool(ret, ready);
    rpc_w_u32(ret, (uint32_t)(esp_timer_get_time() / 1000));
    rpc_w_u16(ret, (uint16_t)devices_count());

    /* A trip is the firmware having stopped the machine on its own. Nothing
     * else reports it, and a scan that ended early is a scan someone will want
     * to explain. */
    rpc_w_u32(ret, watchdog_trips());

    return RPC_OK;
}

/*
 * What the board actually has, so a diagnostic loops over it instead of
 * hardcoding one driver. A bench board with one driver and the carrier with
 * three answer the same question, and the same script covers both.
 */
static rpc_status_t sys_devices(rpc_reader_t *args, rpc_writer_t *ret)
{
    (void)args;

    size_t n = devices_count();
    rpc_w_u16(ret, (uint16_t)n);

    for (size_t i = 0; i < n; i++) {
        const tmc2209_t *dev = devices_at(i);

        uint8_t wired = 0;
        for (int line = 0; line < TMC2209_LINE_COUNT; line++) {
            if (dev && tmc2209_line_is_wired(dev, (tmc2209_line_t)line)) {
                wired |= TMC2209_LINE_BIT(line);
            }
        }

        rpc_w_str(ret, devices_name(i));
        rpc_w_u8(ret, dev ? dev->addr : 0u);
        rpc_w_u8(ret, wired);
        rpc_w_bool(ret, dev != NULL && dev->bus != NULL);
        rpc_w_bool(ret, dev != NULL && dev->stepgen != NULL);
    }

    return RPC_OK;
}

const rpc_handler_fn rpc_sys_methods[RPC_SYS_COUNT] = {
    [RPC_SYS_VERSION] = sys_version,
    [RPC_SYS_STATE]   = sys_state,
    [RPC_SYS_DEVICES] = sys_devices,
};
