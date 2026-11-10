/**
 * @file rpc_trip.h
 * @brief Stops every drive when the PC goes quiet during motion, or when it asks.
 */

#ifndef RPC_TRIP_H
#define RPC_TRIP_H

#include <stdbool.h>
#include <stdint.h>

#include "fw_api.h"

/** How long a moving board waits for a keepalive. */
#define RPC_KEEPALIVE_WITHIN_MS 500U

/** @brief Records that a keepalive arrived. */
void rpc_keepalive_heard(uint32_t now_ms);

/** @brief The deadline a reply carries. The clock starts when motion is first seen. */
uint16_t rpc_keepalive_within_ms(uint32_t now_ms);

/** @brief Halts every drive and releases them once nothing is pulsing. Keeps the first reason. */
void rpc_trip(rpc_trip_reason_t reason, uint8_t detail, bool immediate);

/** @brief Clears the trip. False while a halted drive is still pulsing. */
bool rpc_untrip(void);

/** @brief Trips on a missed keepalive and finishes a pending release. */
void rpc_trip_update(uint32_t now_ms);

/** @brief Why the board is tripped, or RPC_TRIP_NONE. */
rpc_trip_reason_t rpc_trip_reason(void);

/** @brief What `sys.trip` was given. */
uint8_t rpc_trip_detail(void);

#endif /* RPC_TRIP_H */
