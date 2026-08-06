/**
 * @file rpc_relay.c
 * @brief The PC assembles the datagram; this only puts it on the wire.
 *
 * A bridge, so it knows both libraries and nothing about ESP-IDF. That is what
 * lets `test/unit` compile it against the mock driver, where a bad CRC or a
 * silent reply can be produced on demand and a real driver's cannot.
 *
 * Nothing here judges the reply. That is the whole point of the tier: the
 * caller is diagnosing a driver, and an opinion from the library would be the
 * thing under suspicion. What comes back is bytes and a count.
 *
 * Why the transaction's outcome travels as a field rather than as the frame's
 * status is written down beside @ref rpc_relay_send_ret, where the shape it
 * explains actually lives.
 */

#include <stddef.h>

#include "devices.h"
#include "fw_api.h"
#include "rpc_methods.h"
#include "rpc_status.h"
#include "tmc2209.h"
#include "tmc2209_frame.h"

/*
 * A datagram the library did not build is one it cannot account for: it may
 * have written a register we believe we know, and the cache has no way to
 * tell. So a send voids the owned slots.
 *
 * A well-formed read request is the one exception, and it is worth making
 * because polling registers by hand is most of what this tier is for. Four
 * bytes with the write flag clear cannot change anything in the driver.
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

    /* The count is inside the payload, so dispatch could only check that a
     * head arrived. This is the exact length, and the one line it costs. */
    if (args_len != sizeof(*in) + in->count) {
        return RPC_BAD_FRAME;
    }

    if (in->count == 0 || in->count > RPC_RELAY_MAX_BYTES || in->reply_len > RPC_RELAY_MAX_BYTES) {
        return RPC_ARG;
    }

    tmc2209_t *dev = devices_at(in->idx);
    if (dev == NULL) {
        return RPC_ARG;
    }
    if (dev->uart == NULL) {
        return RPC_NO_BACKEND;
    }

    /* Straight into the reply frame. The library's out-parameter is the reply's
     * own storage, so nothing is staged and nothing is copied afterwards. */
    size_t        rx_got = 0;
    tmc2209_err_t err    = tmc2209_uart_send(
        dev->uart, in->tx, in->count, (in->reply_len > 0) ? out->rx : NULL, in->reply_len, &rx_got);

    if (!changes_nothing(in->tx, in->count)) {
        tmc2209_invalidate_owned(dev);
    }

    /* Always this shape. No bytes back is an answer, not a gap. */
    out->outcome = (uint8_t)rpc_status_of_err(err);
    out->count   = (uint8_t)rx_got;

    *ret_len = offsetof(rpc_relay_send_ret, rx) + rx_got;
    return RPC_OK;
}

const rpc_method_t rpc_relay_methods[RPC_RELAY_COUNT] = {
    [RPC_RELAY_SEND] = RPC_METHOD_VAR(relay_send),
};
