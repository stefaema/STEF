#include "tmc2209_err.h"

const char *tmc2209_strerror(tmc2209_err_t err)
{
    switch (err) {
    /* clang-format off */
    case TMC2209_OK:               return "ok";
    case TMC2209_ERR_ARG:          return "bad argument";
    case TMC2209_ERR_TX_TIMEOUT:   return "tx timeout (port took fewer bytes than given)";
    case TMC2209_ERR_RX_TIMEOUT:   return "rx timeout (port gave fewer bytes than asked)";
    case TMC2209_ERR_IO:           return "port I/O failure";
    case TMC2209_ERR_ECHO:         return "echo mismatch (bus collision?)";
    case TMC2209_ERR_PREAMBLE:     return "bad preamble: sync or master address wrong";
    case TMC2209_ERR_CRC:          return "CRC mismatch";
    case TMC2209_ERR_REG:          return "reply for unexpected register";
    case TMC2209_ERR_NO_ACK:       return "IFCNT did not advance enough";
    case TMC2209_ERR_ACCESS:       return "access violation";
    case TMC2209_ERR_NO_BACKEND:   return "no backend attached for this call";
    case TMC2209_ERR_UNWIRED:      return "line not connected on this board";
    case TMC2209_ERR_INVALID_SLOT: return "cache slot invalid";
    case TMC2209_ERR_MISMATCH:     return "device disagrees with cache";
    case TMC2209_ERR_BUSY:         return "a run is in flight";
    case TMC2209_ERR_IDLE:         return "no run is in flight";
    case TMC2209_ERR_RATE:         return "rate beyond what this stepgen can emit";
    /* clang-format on */
    }
    return "unknown";
}
