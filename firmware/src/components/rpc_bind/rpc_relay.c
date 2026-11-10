/**
 * @file rpc_relay.c
 * @brief The PC assembles the datagram; this only puts it on the wire.
 *
 * Knows both libraries and nothing of ESP-IDF, so `test/unit` builds it against
 * the mock driver.
 *
 * The reply is not judged, since the caller is diagnosing the driver. What comes
 * back is bytes and a count. Why the outcome is a field is noted at
 * @ref rpc_relay_send_ret.
 */

#include <stddef.h>

#include "devices.h"
#include "fw_api.h"
#include "rpc_methods.h"
#include "rpc_status.h"
#include "tmc2209.h"
#include "tmc2209_frame.h"

/*
 * Checks if the request is a read, which is the only kind of request that
 * does not change the device's state. The library's own `tmc2209_uart_send`
 * function does not know this, and the relay needs to know it to invalidate
 * the device's owned state only when a write has been sent.
 */
static bool changes_nothing(const uint8_t *tx, size_t tx_len)
{
    if (tx_len != TMC2209_READ_REQ_LEN) {
        return false;
    }
    return (tx[2] & TMC2209_WRITE_FLAG) == 0U;
}

static rpc_status_t relay_send(const void *args, size_t args_len, void *ret, size_t *ret_len)
{
    const rpc_relay_send_args *in  = args;
    rpc_relay_send_ret        *out = ret;

    /* The count is inside the payload, so dispatch could only check that the head
     * arrived. This checks the exact length. */
    if (args_len != sizeof(*in) + in->count) {
        return RPC_BAD_FRAME;
    }

    if (in->count == 0 || in->count > RPC_RELAY_MAX_BYTES || in->reply_len > RPC_RELAY_MAX_BYTES) {
        return RPC_ARG;
    }

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return rpc_status_of_missing_device();
    }
    if (dev->uart == NULL) {
        return RPC_NO_BACKEND;
    }

    /* Straight into the reply frame, so nothing is copied. */
    size_t        rx_got = 0;
    tmc2209_err_t err    = tmc2209_uart_send(
        dev->uart, in->tx, in->count, (in->reply_len > 0) ? out->rx : NULL, in->reply_len, &rx_got);

    if (!changes_nothing(in->tx, in->count)) {
        tmc2209_invalidate_owned(dev);
    }

    /* Always this shape, including when no bytes came back. */
    out->outcome = (uint8_t)rpc_status_of_err(err);
    out->count   = (uint8_t)rx_got;

    *ret_len = offsetof(rpc_relay_send_ret, rx) + rx_got;
    return RPC_OK;
}

const rpc_method_t rpc_relay_methods[RPC_RELAY_COUNT] = {
    [RPC_RELAY_SEND] = RPC_METHOD_VAR(relay_send),
};
