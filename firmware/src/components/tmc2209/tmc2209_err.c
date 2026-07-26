#include "tmc2209_err.h"

const char *tmc2209_strerror(tmc2209_err_t err)
{
    switch (err) {
    case TMC2209_OK:           return "ok";
    case TMC2209_ERR_ARG:      return "bad argument";
    case TMC2209_ERR_TIMEOUT:  return "timeout";
    case TMC2209_ERR_IO:       return "port I/O failure";
    case TMC2209_ERR_ECHO:     return "echo mismatch (bus collision?)";
    case TMC2209_ERR_SYNC:     return "bad sync or master address";
    case TMC2209_ERR_CRC:      return "CRC mismatch";
    case TMC2209_ERR_REG:      return "reply for unexpected register";
    case TMC2209_ERR_NO_ACK:   return "IFCNT did not advance";
    case TMC2209_ERR_ACCESS:   return "register access violation";
    case TMC2209_ERR_INVALID_SLOT:    return "cache slot invalid";
    case TMC2209_ERR_MISMATCH: return "device disagrees with cache";
    }
    return "unknown";
}
