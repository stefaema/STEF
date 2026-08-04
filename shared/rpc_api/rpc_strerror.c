#include "rpc_api.h"

const char *rpc_strerror(rpc_status_t status)
{
    switch (status) {
    case RPC_OK:           return "ok";

    case RPC_ARG:          return "bad argument";
    case RPC_TX_TIMEOUT:   return "tx timeout";
    case RPC_RX_TIMEOUT:   return "rx timeout (driver stayed silent)";
    case RPC_IO:           return "UART peripheral failure";
    case RPC_ECHO:         return "echo mismatch (check UART line)";
    case RPC_SYNC:         return "reply sync byte or master address wrong";
    case RPC_CRC:          return "CRC mismatch";
    case RPC_REG:          return "reply for a register that was not asked about";
    case RPC_NO_ACK:       return "IFCNT did not account for the writes issued";
    case RPC_ACCESS:       return "access policy forbids this";
    case RPC_NO_BACKEND:   return "no backend attached to carry the call out";
    case RPC_UNWIRED:      return "line not connected on this board";
    case RPC_INVALID_SLOT: return "cached value cannot be believed";
    case RPC_MISMATCH:     return "device disagrees with the cache";
    case RPC_BUSY:         return "a run is in flight";
    case RPC_IDLE:         return "no run is in flight";
    case RPC_RATE:         return "rate beyond what this stepgen can emit";
    case RPC_REFUSED:      return "refused: unsafe in the present state";

    case RPC_NO_METHOD:    return "no such namespace, or no such method in it";
    case RPC_BAD_FRAME:    return "payload is not the length this method takes";
    case RPC_INTERNAL:     return "the responder failed for its own reasons";

    default:               return "unknown";
    }
}
