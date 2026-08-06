#include "rpc_frame.h"

#include "crc16.h"

/*
 * The CRC covers the header and the payload together, so it is computed after
 * the header is in place and never before. Appended low byte first, like every
 * other multi-byte value on this wire.
 */
static size_t seal(rpc_buf_t *b, size_t payload_len)
{
    if (payload_len > RPC_MAX_PAYLOAD) {
        return 0;
    }

    size_t   body = RPC_HDR_LEN + payload_len;
    uint16_t crc  = crc16_ccitt(b->bytes, body);

    /* Add CRC bytes to the now sealed frame */
    b->bytes[body]     = (uint8_t)(crc & 0xFFU);
    b->bytes[body + 1] = (uint8_t)((crc >> 8) & 0xFFU);

    return body + RPC_CRC_LEN;
}

/*
 * The header goes on as a whole compound literal, which zeroes its padding
 * members along with the rest. Two identical calls produce two identical CRCs.
 */
size_t rpc_frame_seal_req(rpc_buf_t *b, uint16_t id, uint8_t ns, uint8_t method, size_t payload_len)
{
    if (b == NULL) {
        return 0;
    }

    b->req = (rpc_req_hdr_t){
        .type   = (uint8_t)RPC_FRAME_REQ,
        .ns     = ns,
        .method = method,
        .id     = id,
    };

    return seal(b, payload_len);
}

size_t rpc_frame_seal_rep(rpc_buf_t *b, uint16_t id, rpc_status_t status, size_t payload_len)
{
    if (b == NULL) {
        return 0;
    }

    b->rep = (rpc_rep_hdr_t){
        .type   = (uint8_t)RPC_FRAME_REP,
        .status = (uint8_t)status,
        .id     = id,
    };

    return seal(b, payload_len);
}

size_t rpc_frame_seal_log(rpc_buf_t *b, uint8_t level, uint32_t uptime_ms, size_t payload_len)
{
    if (b == NULL) {
        return 0;
    }

    b->log = (rpc_log_hdr_t){
        .type      = (uint8_t)RPC_FRAME_LOG,
        .level     = level,
        .uptime_ms = uptime_ms,
    };

    return seal(b, payload_len);
}

bool rpc_frame_open(const void *buf, size_t len, rpc_view_t *out)
{
    if (buf == NULL || out == NULL) {
        return false;
    }

    /* A header and a CRC is the shortest thing that can be called a frame, and
     * anything longer than the buffer it arrived in cannot be one either. */
    if (len < RPC_HDR_LEN + RPC_CRC_LEN || len > RPC_MAX_FRAME) {
        return false;
    }

    const uint8_t *bytes = buf;
    size_t         body  = len - RPC_CRC_LEN;

    uint16_t want = (uint16_t)((uint16_t)bytes[body] | ((uint16_t)bytes[body + 1] << 8));
    if (crc16_ccitt(bytes, body) != want) {
        return false;
    }

    uint8_t type = bytes[0];
    if (type != RPC_FRAME_REQ && type != RPC_FRAME_REP && type != RPC_FRAME_LOG) {
        return false;
    }

    out->type        = type;
    out->hdr         = buf;
    out->payload     = &bytes[RPC_HDR_LEN];
    out->payload_len = body - RPC_HDR_LEN;

    return true;
}
