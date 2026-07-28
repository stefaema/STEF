/**
 * @file rpc_methods.h
 * @brief The method tables this image serves, for the root that registers them.
 *
 * The `rpc` component names no handler, so something has to. These are what it
 * is handed, and `dev_main.c` is where the handing happens.
 *
 * Split by namespace and not by file for a reason: `sys` reaches into ESP-IDF
 * for the app descriptor and the uptime, while `raw` and `passthrough` reach
 * only into `tmc2209.h`. That is what lets the second pair be compiled on the
 * host by `test/unit` and the first not.
 */

#ifndef RPC_METHODS_H
#define RPC_METHODS_H

#include "rpc_dispatch.h"
#include "rpc_proto.h"

/** @brief `sys` methods, indexed by @ref rpc_sys_method_t. */
extern const rpc_handler_fn rpc_sys_methods[RPC_SYS_COUNT];

/** @brief `passthrough` methods, indexed by @ref rpc_pt_method_t. */
extern const rpc_handler_fn rpc_passthrough_methods[RPC_PT_COUNT];

/** @brief `raw` methods, indexed by @ref rpc_raw_method_t. */
extern const rpc_handler_fn rpc_raw_methods[RPC_RAW_COUNT];

#endif /* RPC_METHODS_H */
