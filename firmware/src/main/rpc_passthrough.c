/**
 * @file rpc_passthrough.c
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
 * ## Why the outcome is a value and not the frame's status
 *
 * Passthrough reports what happened; raw reports whether it worked. A driver
 * that stayed silent, or one whose echo came back altered, is an *answer* here
 * and not a failure, and the bytes that did arrive are the evidence the caller
 * asked for. But a reply frame carrying a failing status is rewound by
 * dispatch, precisely so a handler cannot leave half an answer behind.
 *
 * So the wire's outcome travels as a field. The frame's status then reports
 * only whether the call was well formed, which is the one thing this tier is
 * still entitled to have an opinion about.
 */

#include "devices.h"
#include "rpc_dispatch.h"
#include "rpc_methods.h"
#include "rpc_proto.h"
#include "rpc_status.h"
#include "rpc_wire.h"
#include "tmc2209.h"
#include "tmc2209_frame.h"

/** The part's longest datagram, both directions. */
#define PT_MAX_BYTES 32

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
    return (tx[2] & TMC2209_WRITE_FLAG) == 0u;
}

static rpc_status_t pt_send(rpc_reader_t *args, rpc_writer_t *ret)
{
    uint8_t idx       = rpc_r_u8(args);
    uint8_t reply_len = rpc_r_u8(args);

    size_t         tx_len = 0;
    const uint8_t *tx     = rpc_r_bytes(args, &tx_len);

    if (!args->ok) {
        return RPC_BAD_FRAME;
    }
    if (tx == NULL || tx_len == 0 || tx_len > PT_MAX_BYTES ||
        reply_len > PT_MAX_BYTES) {
        return RPC_ARG;
    }

    tmc2209_t *dev = devices_at(idx);
    if (dev == NULL) {
        return RPC_ARG;
    }
    if (dev->bus == NULL) {
        return RPC_NO_BACKEND;
    }

    uint8_t rx[PT_MAX_BYTES];
    size_t  rx_got = 0;

    tmc2209_err_t err = tmc2209_bus_send(dev->bus, tx, tx_len,
                                         reply_len ? rx : NULL, reply_len, &rx_got);

    if (!changes_nothing(tx, tx_len)) {
        tmc2209_invalidate_owned(dev);
    }

    /* Always this shape. An empty byte string is an answer, not a gap. */
    rpc_w_u8(ret, (uint8_t)rpc_status_of_err(err));
    rpc_w_bytes(ret, rx, rx_got);

    return RPC_OK;
}

const rpc_handler_fn rpc_passthrough_methods[RPC_PT_COUNT] = {
    [RPC_PT_SEND] = pt_send,
};
