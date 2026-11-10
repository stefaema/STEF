#include "rpc_trip.h"

#include "devices.h"
#include "tmc2209.h"

static rpc_trip_reason_t s_reason;
static uint8_t           s_detail;
static bool              s_released = true;

static bool     s_watching;
static uint32_t s_heard_ms;

static bool pulsing(tmc2209_t *dev)
{
    bool running = false;
    return tmc2209_is_running(dev, &running) == TMC2209_OK && running;
}

/* An uncached VACTUAL counts as zero, so a board that was never brought up does
   not trip when the PC disconnects. */
static bool velocity_set(tmc2209_t *dev)
{
    uint32_t v = 0;
    return tmc2209_read(dev, TMC2209_VACTUAL, &v) == TMC2209_OK && v != 0U;
}

static bool anything_moving(void)
{
    for (size_t i = 0; i < devices_count(); i++) {
        tmc2209_t *dev = devices_at(i);
        if (dev != NULL && (pulsing(dev) || velocity_set(dev))) {
            return true;
        }
    }
    return false;
}

static void release_once_still(void)
{
    if (s_released || anything_moving()) {
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

static bool watching(uint32_t now_ms)
{
    if (s_reason != RPC_TRIP_NONE || !anything_moving()) {
        s_watching = false;
        return false;
    }
    if (!s_watching) {
        s_watching = true;
        s_heard_ms = now_ms;
    }
    return true;
}

void rpc_keepalive_heard(uint32_t now_ms)
{
    s_heard_ms = now_ms;
}

uint16_t rpc_keepalive_within_ms(uint32_t now_ms)
{
    return watching(now_ms) ? (uint16_t)RPC_KEEPALIVE_WITHIN_MS : (uint16_t)RPC_KEEPALIVE_NONE;
}

void rpc_trip_set(rpc_trip_reason_t reason, uint8_t detail, bool immediate)
{
    if (s_reason == RPC_TRIP_NONE) {
        s_reason = reason;
        s_detail = detail;
    }
    s_released = false;
    s_watching = false;

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
    if (watching(now_ms) && now_ms - s_heard_ms > RPC_KEEPALIVE_WITHIN_MS) {
        rpc_trip_set(RPC_TRIP_KEEPALIVE, 0, false);
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
