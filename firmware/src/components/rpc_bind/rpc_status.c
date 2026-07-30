#include "rpc_status.h"

rpc_status_t rpc_status_of_err(tmc2209_err_t err)
{
    switch (err) {
    case TMC2209_OK:                return RPC_OK;
    case TMC2209_ERR_ARG:           return RPC_ARG;
    case TMC2209_ERR_TX_TIMEOUT:    return RPC_TX_TIMEOUT;
    case TMC2209_ERR_RX_TIMEOUT:    return RPC_RX_TIMEOUT;
    case TMC2209_ERR_IO:            return RPC_IO;
    case TMC2209_ERR_ECHO:          return RPC_ECHO;
    case TMC2209_ERR_PREAMBLE:      return RPC_SYNC;
    case TMC2209_ERR_CRC:           return RPC_CRC;
    case TMC2209_ERR_REG:           return RPC_REG;
    case TMC2209_ERR_NO_ACK:        return RPC_NO_ACK;
    case TMC2209_ERR_ACCESS:        return RPC_ACCESS;
    case TMC2209_ERR_NO_BACKEND:    return RPC_NO_BACKEND;
    case TMC2209_ERR_UNWIRED:       return RPC_UNWIRED;
    case TMC2209_ERR_INVALID_SLOT:  return RPC_INVALID_SLOT;
    case TMC2209_ERR_MISMATCH:      return RPC_MISMATCH;
    case TMC2209_ERR_BUSY:          return RPC_BUSY;
    case TMC2209_ERR_IDLE:          return RPC_IDLE;
    case TMC2209_ERR_RATE:          return RPC_RATE;
    }

    /* No default above, so a new library error is a compile warning here
     * rather than a value that quietly becomes RPC_INTERNAL on the wire. */
    return RPC_INTERNAL;
}
