#include "rpc_trip.h"

#include "devices.h"
#include "tmc2209.h"

static rpc_trip_reason_t s_reason;
static uint8_t           s_detail;
static bool              s_released = true;

static bool     s_keepalive_required;
static uint32_t s_heard_ms;

/* No stepgen means no pulses. Any other failure might be pulsing */
static bool anything_pulsing(void)
{
    for (size_t i = 0; i < devices_count(); i++) {
        tmc2209_t *dev = devices_at(i);
        if (dev == NULL) {
            continue;
        }

        bool          pulsing = false;
        tmc2209_err_t err     = tmc2209_is_running(dev, &pulsing);
        if (pulsing || (err != TMC2209_OK && err != TMC2209_ERR_NO_BACKEND)) {
            return true;
        }
    }
    return false;
}

/* An unknown VACTUAL counts as moving while the driver is enabled */
static bool anything_moving(void)
{
    if (anything_pulsing()) {
        return true;
    }

    for (size_t i = 0; i < devices_count(); i++) {
        tmc2209_t *dev = devices_at(i);
        if (dev == NULL) {
            continue;
        }

        uint32_t      vactual = 0;
        tmc2209_err_t err     = tmc2209_read(dev, TMC2209_VACTUAL, &vactual);
        if (err == TMC2209_OK && vactual != 0U) {
            return true;
        }

        bool enabled = true;
        (void)tmc2209_is_enabled(dev, &enabled);
        if (err != TMC2209_OK && enabled) {
            return true;
        }
    }
    return false;
}

/* Only step runs need to finish braking. ENN high stops VACTUAL at once */
static void release_once_still(void)
{
    if (s_released || anything_pulsing()) {
        return;
    }
    for (size_t i = 0; i < devices_count(); i++) {
        tmc2209_t *dev = devices_at(i);
        if (dev != NULL) {
            (void)tmc2209_enable(dev, false);
        }
    }
    s_released = true;
}

/* Starts the deadline the first time motion is seen */
static bool keepalive_required(uint32_t now_ms)
{
    if (s_reason != RPC_TRIP_NONE || !anything_moving()) {
        s_keepalive_required = false;
        return false;
    }
    if (!s_keepalive_required) {
        s_keepalive_required = true;
        s_heard_ms           = now_ms;
    }
    return true;
}

void rpc_keepalive_heard(uint32_t now_ms)
{
    s_heard_ms = now_ms;
}

uint16_t rpc_keepalive_within_ms(uint32_t now_ms)
{
    return keepalive_required(now_ms) ? (uint16_t)RPC_KEEPALIVE_WITHIN_MS
                                      : (uint16_t)RPC_KEEPALIVE_NONE;
}

void rpc_trip(rpc_trip_reason_t reason, uint8_t detail, bool immediate)
{
    if (s_reason == RPC_TRIP_NONE) {
        s_reason = reason;
        s_detail = detail;
    }
    s_released           = false;
    s_keepalive_required = false;

    for (size_t i = 0; i < devices_count(); i++) {
        tmc2209_t *dev = devices_at(i);
        if (dev != NULL) {
            (void)tmc2209_halt(dev, immediate);
            (void)tmc2209_set_velocity(dev, 0);
        }
    }

    release_once_still();
}

bool rpc_untrip(void)
{
    release_once_still();
    if (!s_released) {
        return false;
    }
    s_reason = RPC_TRIP_NONE;
    s_detail = 0;
    return true;
}

void rpc_trip_update(uint32_t now_ms)
{
    if (keepalive_required(now_ms) && now_ms - s_heard_ms > RPC_KEEPALIVE_WITHIN_MS) {
        rpc_trip(RPC_TRIP_KEEPALIVE, 0, false);
    }
    release_once_still();
}

rpc_trip_reason_t rpc_trip_reason(void)
{
    return s_reason;
}

uint8_t rpc_trip_detail(void)
{
    return s_detail;
}
