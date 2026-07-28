/*
 * fake_watchdog.c: the deadline, host side.
 *
 * `rpc_raw.c` arms the watchdog when a move starts, so the host build needs
 * the symbol. What it does not need is the behaviour: the real one halts and
 * disables a driver, which on a test bench with no clock and no motor would be
 * enforcing a deadline against a run that is not happening.
 *
 * Recording the arm is still worth doing, because "did the move arm it" is a
 * question a test can ask.
 */

#include "watchdog.h"

static size_t   s_last_dev;
static uint32_t s_last_deadline;
static unsigned s_arms;

void watchdog_arm(size_t dev, uint32_t deadline_ms)
{
    s_last_dev      = dev;
    s_last_deadline = deadline_ms;
    s_arms++;
}

void watchdog_feed(void) {}

void watchdog_tick(bool link_up)
{
    (void)link_up;
}

uint32_t watchdog_trips(void)
{
    return 0;
}

/* For a test that wants to assert a move armed the deadline it asked for. */
unsigned fake_watchdog_arms(void)
{
    return s_arms;
}

size_t fake_watchdog_last_dev(void)
{
    return s_last_dev;
}

uint32_t fake_watchdog_last_deadline(void)
{
    return s_last_deadline;
}
