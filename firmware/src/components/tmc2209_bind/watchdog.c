#include "watchdog.h"

#include "devices.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "tmc2209.h"

#define WATCHDOG_MAX_DEVICES 4

static const char *TAG = "watchdog";

static uint32_t s_deadline_ms[WATCHDOG_MAX_DEVICES]; /* 0 when not armed */
static uint32_t s_fed_at_ms;
static uint32_t s_trips;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

void watchdog_arm(size_t dev, uint32_t deadline_ms)
{
    if (dev >= WATCHDOG_MAX_DEVICES) {
        return;
    }

    if (deadline_ms == 0) {
        deadline_ms = WATCHDOG_DEFAULT_MS;
    } else if (deadline_ms > WATCHDOG_MAX_MS) {
        deadline_ms = WATCHDOG_MAX_MS;
    }

    s_deadline_ms[dev] = deadline_ms;

    /* The request that armed it is also the most recent thing the PC said. */
    s_fed_at_ms = now_ms();
}

void watchdog_feed(void)
{
    s_fed_at_ms = now_ms();
}

uint32_t watchdog_trips(void)
{
    return s_trips;
}

/*
 * Halt and disable, in that order, and both regardless of what either returns.
 * Halting alone would leave the power stage holding the film under tension
 * with nobody watching; dropping it is unambiguously safe for the mechanism,
 * and slack film is a recoverable problem in a way that a runaway reel is not.
 *
 * The halt is immediate rather than ramped. A ramp is a courtesy to the motor,
 * and the case this exists for is one where nobody is left to be courteous to.
 */
static void stop_everything(const char *why)
{
    s_trips++;

    for (size_t i = 0; i < WATCHDOG_MAX_DEVICES; i++) {
        if (s_deadline_ms[i] == 0) {
            continue;
        }

        tmc2209_t *dev = devices_at(i);
        if (dev != NULL) {
            (void)tmc2209_halt(dev, true);
            (void)tmc2209_enable(dev, false);
        }

        s_deadline_ms[i] = 0;
    }

    ESP_LOGW(TAG, "%s: halted and disabled everything that was moving", why);
}

/*
 * A device that finished its run stops being watched. The question is asked
 * with tmc2209_is_running() and not with tmc2209_get_motion_report(), because the
 * latter also collects the run's count, and a supervisor that collected it
 * would let the next move go ahead on an acknowledgement its owner never made.
 */
static bool disarm_the_stopped(void)
{
    bool any_armed = false;

    for (size_t i = 0; i < WATCHDOG_MAX_DEVICES; i++) {
        if (s_deadline_ms[i] == 0) {
            continue;
        }

        tmc2209_t *dev = devices_at(i);
        if (dev == NULL) {
            s_deadline_ms[i] = 0;
            continue;
        }

        bool running = false;
        if (tmc2209_is_running(dev, &running) == TMC2209_OK && !running) {
            s_deadline_ms[i] = 0;
            continue;
        }

        any_armed = true;
    }

    return any_armed;
}

/* The shortest deadline among the armed devices governs, because it is the one
 * whose owner expected to hear back soonest. */
static uint32_t tightest_deadline(void)
{
    uint32_t tightest = WATCHDOG_MAX_MS;

    for (size_t i = 0; i < WATCHDOG_MAX_DEVICES; i++) {
        if (s_deadline_ms[i] != 0 && s_deadline_ms[i] < tightest) {
            tightest = s_deadline_ms[i];
        }
    }

    return tightest;
}

void watchdog_tick(bool link_up)
{
    if (!disarm_the_stopped()) {
        return; /* nothing is moving, so nothing is in danger */
    }

    /*
     * Two failures, two signals. An unplugged cable is visible immediately and
     * there is nothing to gain by waiting out a deadline for it. A PC that
     * crashed or hung with the cable still in is invisible to the bus and is
     * exactly what the deadline catches.
     */
    if (!link_up) {
        stop_everything("link down");
        return;
    }

    if (now_ms() - s_fed_at_ms > tightest_deadline()) {
        stop_everything("no request within the deadline");
    }
}
