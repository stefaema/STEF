/**
 * @file rpc_status.h
 * @brief Bridges the gap between TMC2209 errors and RPC errors.
 */

#ifndef RPC_STATUS_H
#define RPC_STATUS_H

#include "fw_api.h"
#include "tmc2209_err.h"

/** @brief @p err as the status a reply carries. */
rpc_status_t rpc_status_of_err(tmc2209_err_t err);

#endif /* RPC_STATUS_H */
