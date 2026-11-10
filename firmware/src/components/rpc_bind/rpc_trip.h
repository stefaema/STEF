#ifndef RPC_TRIP_H
#define RPC_TRIP_H

#include <stdbool.h>
#include <stdint.h>

#include "fw_api.h"

#define RPC_KEEPALIVE_WITHIN_MS 500U

void     rpc_keepalive_heard(uint32_t now_ms);
uint16_t rpc_keepalive_within_ms(uint32_t now_ms);

void rpc_trip_set(rpc_trip_reason_t reason, uint8_t detail, bool immediate);
bool rpc_trip_clear(void);
void rpc_trip_update(uint32_t now_ms);

rpc_trip_reason_t rpc_trip_reason(void);
uint8_t           rpc_trip_detail(void);

#endif /* RPC_TRIP_H */
