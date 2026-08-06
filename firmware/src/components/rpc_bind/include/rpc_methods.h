/**
 * @file rpc_methods.h
 * @brief The method tables this image serves, for the root that registers them.
 *
 * The `rpc` component names no handler, so something has to. These are what it
 * is handed, and `dev_main.c` is where the handing happens.
 *
 * Each table is where its namespace's payload sizes are taken, since `sizeof`
 * is evaluated here in `rpc_bind` where those structs are visible. The component
 * receives integers and still names no type of ours.
 *
 * Split by namespace and not by file for a reason: `sys` reaches into ESP-IDF
 * for the app descriptor and the uptime, while `raw` and `relay` reach
 * only into `tmc2209.h`. That is what lets the second pair be compiled on the
 * host by `test/unit` and the first not.
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
