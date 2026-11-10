/**
 * @file rpc_methods.h
 * @brief The method tables this image serves, for the root that registers them.
 *
 * Payload sizes are taken here, where the structs are visible, so the `rpc`
 * component gets integers and names no type of ours.
 *
 * Split by namespace, since `sys` reaches into ESP-IDF while `raw` and `relay`
 * only reach `tmc2209.h`, so `test/unit` can build those two on the host.
 */

#ifndef RPC_METHODS_H
#define RPC_METHODS_H

#include "fw_api.h"
#include "rpc_dispatch.h"

/** @brief `sys` methods, indexed by @ref rpc_sys_method_t. */
extern const rpc_method_t rpc_sys_methods[RPC_SYS_COUNT];

/** @brief `relay` methods, indexed by @ref rpc_relay_method_t. */
extern const rpc_method_t rpc_relay_methods[RPC_RELAY_COUNT];

/** @brief `raw` methods, indexed by @ref rpc_raw_method_t. */
extern const rpc_method_t rpc_raw_methods[RPC_RAW_COUNT];

#endif /* RPC_METHODS_H */
