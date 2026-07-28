#include "rpc_wire.h"

#include <string.h>

#include "crc16.h"

/* ── Writing ────────────────────────────────────────────────────────────── */

/* Returns the place to write @p n bytes, or NULL once the writer has failed.
 * Failing here poisons the writer, which is what makes every later call a
 * no-op and lets the caller check once. */
static uint8_t *take(rpc_writer_t *w, size_t n)
{
    if (w == NULL || !w->ok) {
        return NULL;
    }
    if (w->len + n > w->cap) {
        w->ok = false;
        return NULL;
    }

    uint8_t *at = w->buf + w->len;
    w->len += n;
    return at;
}

void rpc_w_init(rpc_writer_t *w, uint8_t *buf, size_t cap)
{
    if (w == NULL) {
        return;
    }
    w->buf = buf;
    w->cap = buf ? cap : 0;
    w->len = 0;
    w->ok  = (buf != NULL);
}

void rpc_w_u8(rpc_writer_t *w, uint8_t v)
{
    uint8_t *at = take(w, 1);
    if (at) {
        at[0] = v;
    }
}

void rpc_w_u16(rpc_writer_t *w, uint16_t v)
{
    uint8_t *at = take(w, 2);
    if (at) {
        at[0] = (uint8_t)(v & 0xFFu);
        at[1] = (uint8_t)((v >> 8) & 0xFFu);
    }
}

void rpc_w_u32(rpc_writer_t *w, uint32_t v)
{
    uint8_t *at = take(w, 4);
    if (at) {
        at[0] = (uint8_t)(v & 0xFFu);
        at[1] = (uint8_t)((v >> 8) & 0xFFu);
        at[2] = (uint8_t)((v >> 16) & 0xFFu);
        at[3] = (uint8_t)((v >> 24) & 0xFFu);
    }
}

/* Two's complement, which both ends already are. The cast is the whole
 * conversion; nothing about the sign travels separately. */
void rpc_w_i32(rpc_writer_t *w, int32_t v)
{
    rpc_w_u32(w, (uint32_t)v);
}

void rpc_w_bool(rpc_writer_t *w, bool v)
{
    rpc_w_u8(w, v ? 1u : 0u);
}

void rpc_w_bytes(rpc_writer_t *w, const uint8_t *src, size_t len)
{
    if (w == NULL || !w->ok) {
        return;
    }
    if (len > 0xFFFFu || (src == NULL && len > 0)) {
        w->ok = false;
        return;
    }

    rpc_w_u16(w, (uint16_t)len);

    uint8_t *at = take(w, len);
    if (at && len > 0) {
        memcpy(at, src, len);
    }
}

void rpc_w_str(rpc_writer_t *w, const char *s)
{
    if (s == NULL) {
        rpc_w_u16(w, 0);
        return;
    }
    rpc_w_bytes(w, (const uint8_t *)s, strlen(s));
}

/* ── Reading ────────────────────────────────────────────────────────────── */

static const uint8_t *give(rpc_reader_t *r, size_t n)
{
    if (r == NULL || !r->ok) {
        return NULL;
    }
    if (r->pos + n > r->len) {
        r->ok = false;
        return NULL;
    }

    const uint8_t *at = r->buf + r->pos;
    r->pos += n;
    return at;
}

void rpc_r_init(rpc_reader_t *r, const uint8_t *buf, size_t len)
{
    if (r == NULL) {
        return;
    }
    r->buf = buf;
    r->len = buf ? len : 0;
    r->pos = 0;
    r->ok  = (buf != NULL);
}

uint8_t rpc_r_u8(rpc_reader_t *r)
{
    const uint8_t *at = give(r, 1);
    return at ? at[0] : 0u;
}

uint16_t rpc_r_u16(rpc_reader_t *r)
{
    const uint8_t *at = give(r, 2);
    if (!at) {
        return 0u;
    }
    return (uint16_t)((uint16_t)at[0] | ((uint16_t)at[1] << 8));
}

uint32_t rpc_r_u32(rpc_reader_t *r)
{
    const uint8_t *at = give(r, 4);
    if (!at) {
        return 0u;
    }
    return (uint32_t)at[0] | ((uint32_t)at[1] << 8) | ((uint32_t)at[2] << 16) |
           ((uint32_t)at[3] << 24);
}

int32_t rpc_r_i32(rpc_reader_t *r)
{
    return (int32_t)rpc_r_u32(r);
}

/* Any non-zero is true. A sender that writes 2 is wrong, but rejecting the
 * frame over it would fail a call that is otherwise unambiguous. */
bool rpc_r_bool(rpc_reader_t *r)
{
    return rpc_r_u8(r) != 0u;
}

const uint8_t *rpc_r_bytes(rpc_reader_t *r, size_t *len)
{
    if (len) {
        *len = 0;
    }

    uint16_t n = rpc_r_u16(r);
    const uint8_t *at = give(r, n);
    if (!at) {
        return NULL;
    }

    if (len) {
        *len = n;
    }
    return at;
}

bool rpc_r_done(const rpc_reader_t *r)
{
    return r != NULL && r->ok && r->pos == r->len;
}

/* ── Frames ─────────────────────────────────────────────────────────────── */

void rpc_frame_begin_rep(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint16_t id, rpc_status_t status)
{
    rpc_w_init(w, buf, cap);
    rpc_w_u8(w, (uint8_t)RPC_FRAME_REP);
    rpc_w_u16(w, id);
    rpc_w_u8(w, (uint8_t)status);
}

void rpc_frame_begin_req(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint16_t id, uint8_t ns, uint8_t method)
{
    rpc_w_init(w, buf, cap);
    rpc_w_u8(w, (uint8_t)RPC_FRAME_REQ);
    rpc_w_u16(w, id);
    rpc_w_u8(w, ns);
    rpc_w_u8(w, method);
}

void rpc_frame_begin_log(rpc_writer_t *w, uint8_t *buf, size_t cap,
                         uint8_t level, uint32_t uptime_ms)
{
    rpc_w_init(w, buf, cap);
    rpc_w_u8(w, (uint8_t)RPC_FRAME_LOG);
    rpc_w_u8(w, level);
    rpc_w_u32(w, uptime_ms);
}

void rpc_w_rewind(rpc_writer_t *w, size_t mark)
{
    if (w == NULL || w->buf == NULL || mark > w->cap) {
        return;
    }
    w->len = mark;
    w->ok  = true;
}

/* The status sits at a fixed offset because a reply header is fixed width:
 * type, then id, then status. */
void rpc_frame_set_status(rpc_writer_t *w, rpc_status_t status)
{
    const size_t status_at = 1 + 2;

    if (w == NULL || w->buf == NULL || w->len <= status_at) {
        return;
    }
    w->buf[status_at] = (uint8_t)status;
}

size_t rpc_frame_finish(rpc_writer_t *w)
{
    if (w == NULL || !w->ok) {
        return 0;
    }

    uint16_t crc = crc16_ccitt(w->buf, w->len);
    rpc_w_u16(w, crc);

    return w->ok ? w->len : 0;
}

bool rpc_frame_open(const uint8_t *buf, size_t len, uint8_t *type, rpc_reader_t *r)
{
    if (buf == NULL || type == NULL || r == NULL) {
        return false;
    }

    /* A type byte and a CRC is the shortest thing that can be called a frame. */
    if (len < 3) {
        return false;
    }

    size_t   body = len - 2;
    uint16_t want = (uint16_t)((uint16_t)buf[body] | ((uint16_t)buf[body + 1] << 8));
    if (crc16_ccitt(buf, body) != want) {
        return false;
    }

    if (buf[0] != RPC_FRAME_REQ && buf[0] != RPC_FRAME_REP && buf[0] != RPC_FRAME_LOG) {
        return false;
    }

    *type = buf[0];
    rpc_r_init(r, buf + 1, body - 1);
    return true;
}

bool rpc_req_header(rpc_reader_t *r, rpc_req_t *out)
{
    if (out == NULL) {
        return false;
    }

    out->id     = rpc_r_u16(r);
    out->ns     = rpc_r_u8(r);
    out->method = rpc_r_u8(r);

    return r != NULL && r->ok;
}
