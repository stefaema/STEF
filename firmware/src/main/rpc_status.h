/**
 * @file rpc_status.h
 * @brief The library's error as the wire's status.
 *
 * Two vocabularies that are the same vocabulary. `rpc_proto.h` names its
 * statuses after `TMC2209_ERR_*` on purpose, and still cannot include that
 * header: the wire's values are fixed by the protocol, the library's by its
 * own enum, and neither is entitled to move the other.
 *
 * So the correspondence is written down here, in `main/`, which is the one
 * place allowed to know both. A renumbering, not a translation.
 *
 * Portable by discipline: this file and the other bridges include the two
 * libraries and nothing from ESP-IDF, which is what lets `test/unit` compile
 * them on the host.
 */

#ifndef RPC_STATUS_H
#define RPC_STATUS_H

#include "rpc_proto.h"
#include "tmc2209_err.h"

/** @brief @p err as the status a reply carries. */
rpc_status_t rpc_status_of_err(tmc2209_err_t err);

#endif /* RPC_STATUS_H */
