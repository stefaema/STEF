/**
 * @file watchdog.h
 * @brief Stops the film when the PC stops talking.
 *
 * A run started over RPC outlives the call that started it. So if the
 * orchestrator crashes, or someone trips over the cable, the last thing the
 * firmware was told remains in force and the capstan keeps winding. Nothing in
 * the request/response model notices, because nothing was asked.
 *
 * The control link is therefore a dead-man switch. Any valid request feeds it,
 * which costs nothing because a PC driving a move is already polling one; a
 * dedicated heartbeat would only carry information on the rare occasions there
 * was nothing else to say.
 *
 * ## What it is not
 *
 * Not a task, and not a timer callback. The library is single-owner by design,
 * so a second context calling into a device while the dispatch task is mid
 * transaction would be a data race with a motor attached to it. The check runs
 * in the task that already owns the devices, which is why this is a tick to be
 * called and not a thing that runs by itself.
 *
 * ## What arms it
 *
 * Only a run in flight. An idle board is not in danger, so it never needs the
 * PC to keep talking, and a bench session can sit untouched for an hour.
 *
 * Portable by discipline, so `rpc_raw.c` can arm it and `test/unit` can stub
 * it out.
 */

#ifndef WATCHDOG_H
#define WATCHDOG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/**
 * Long enough to survive the PC, which is what actually goes quiet: a vision
 * pass costs tens of milliseconds, plus GC, plus a scheduler that owes Python
 * nothing. Below about 200 ms this trips on a healthy system eventually, and a
 * false trip mid-scan costs slack film and an aborted pass. A late halt costs
 * millimetres.
 */
#define WATCHDOG_DEFAULT_MS 500u

/** Clamped, so a caller cannot effectively disable it by asking for a year. */
#define WATCHDOG_MAX_MS 5000u

/** How often the tick has to be called for the deadline to mean anything. */
#define WATCHDOG_TICK_MS 50u

/**
 * @brief Puts device @p dev under the deadline, because it is now moving.
 *
 * @param dev          board table index
 * @param deadline_ms  0 for @ref WATCHDOG_DEFAULT_MS, else clamped to
 *                     @ref WATCHDOG_MAX_MS
 */
void watchdog_arm(size_t dev, uint32_t deadline_ms);

/** @brief The PC said something. Called for every request that parsed. */
void watchdog_feed(void);

/**
 * @brief Checks the deadline, and enforces it if it has passed.
 *
 * Disarms any device that has stopped on its own, which is also what settles
 * its odometer. Must be called from the task that owns the devices, about
 * every @ref WATCHDOG_TICK_MS.
 *
 * @param link_up  false when the USB bus is no longer enumerating. An unplugged
 *                 cable is not worth waiting out a timeout for
 */
void watchdog_tick(bool link_up);

/** @brief How many times it has fired since boot. Reported by `sys.state`. */
uint32_t watchdog_trips(void);

#endif /* WATCHDOG_H */
