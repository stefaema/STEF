#include "rpc_link.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "cobs.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "rpc_dispatch.h"
#include "rpc_api.h"
#include "rpc_frame.h"
#include "watchdog.h"

/* Encoded worst case, plus the delimiter that closes the frame. */
#define RPC_ENCODED_MAX (COBS_ENCODED_MAX(RPC_MAX_FRAME) + 1u)

#define RPC_TXQ_DEPTH   6
#define RPC_LOG_MAX     192  /**< one log line, ANSI stripped */
#define RPC_USB_CHUNK   64   /**< a USB full-speed bulk packet */

/**
 * A finished frame waiting for the wire, CRC included and COBS not yet applied.
 *
 * Copied into the queue rather than passed by pointer. It costs a memcpy per
 * frame on a link that moves a few hundred bytes at a time, and it buys the
 * absence of an ownership question: no allocation, no free, no frame still
 * referenced by a task that gave up on it.
 */
typedef struct {
    uint16_t len;
    uint8_t  data[RPC_MAX_FRAME];
} tx_frame_t;

static QueueHandle_t s_txq;
static bool          s_started;

/* ── The single TX owner ────────────────────────────────────────────────── */

/*
 * Replies come from the RX task and logs come from whichever task called
 * ESP_LOGx, so there are two producers and there is exactly one consumer. Two
 * tasks writing the port directly would interleave inside a frame, and the
 * damage would show up as a CRC failure on the PC with nothing pointing back
 * here. Everything therefore goes through this queue, and only this task
 * encodes and writes.
 */
static void tx_task(void *arg)
{
    (void)arg;

    static uint8_t encoded[RPC_ENCODED_MAX];
    tx_frame_t     frame;

    for (;;) {
        if (xQueueReceive(s_txq, &frame, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        size_t n = cobs_encode(frame.data, frame.len, encoded, sizeof(encoded) - 1u);
        if (n == 0) {
            continue; /* cannot happen for a frame that fits; drop rather than send garbage */
        }
        encoded[n++] = 0x00;

        /*
         * A host that is not reading gets a short write and the frame is
         * dropped. Blocking here would stall every reply behind a PC that
         * closed the port, and there is no one to tell about it: this task is
         * what logging would have to go through.
         */
        (void)usb_serial_jtag_write_bytes(encoded, n, pdMS_TO_TICKS(50));
    }
}

/** Hands a finished frame to the TX task. False when the queue is full. */
static bool tx_send(const void *data, size_t len, TickType_t wait)
{
    if (s_txq == NULL || len == 0 || len > RPC_MAX_FRAME) {
        return false;
    }

    tx_frame_t frame;
    frame.len = (uint16_t)len;
    memcpy(frame.data, data, len);

    return xQueueSend(s_txq, &frame, wait) == pdTRUE;
}

/* ── Logging ────────────────────────────────────────────────────────────── */

/*
 * IDF hands the hook a line that is already formatted and already wrapped in
 * colour escapes. The escapes are for a terminal that is no longer on the other
 * end, so they are dropped here rather than shipped and dropped there.
 */
static size_t strip_ansi(const char *src, size_t len, char *dst, size_t cap)
{
    size_t out = 0;

    for (size_t i = 0; i < len && out < cap; i++) {
        if (src[i] == '\033') {
            while (i < len && src[i] != 'm') {
                i++;
            }
            continue;
        }
        if (src[i] == '\r' || src[i] == '\n') {
            continue;
        }
        dst[out++] = src[i];
    }

    return out;
}

/* The level is not passed to the hook, so it is read back off the line IDF
 * formatted: the letter before the timestamp, which nothing else can be. */
static uint8_t level_of(const char *line, size_t len)
{
    for (size_t i = 0; i < len && line[i] != '('; i++) {
        switch (line[i]) {
        case 'E': return 1;
        case 'W': return 2;
        case 'I': return 3;
        case 'D': return 4;
        case 'V': return 5;
        default:  break;
        }
    }
    return 0;
}

static int log_to_link(const char *fmt, va_list ap)
{
    /* An ISR has no business queueing, and ESP_EARLY_LOGx is the only thing
     * that gets here from one. Dropping is better than a crash inside a log. */
    if (xPortInIsrContext()) {
        return 0;
    }

    char raw[RPC_LOG_MAX];
    int  n = vsnprintf(raw, sizeof(raw), fmt, ap);
    if (n <= 0) {
        return n;
    }

    size_t raw_len = ((size_t)n < sizeof(raw)) ? (size_t)n : sizeof(raw) - 1u;

    char   text[RPC_LOG_MAX];
    size_t len = strip_ansi(raw, raw_len, text, sizeof(text));
    if (len == 0) {
        return n;
    }

    /* The text is the whole payload, so its length is the frame's and no count
     * has to travel with it. */
    rpc_buf_t buf;
    memcpy(rpc_payload(&buf), text, len);

    size_t frame_len = rpc_frame_seal_log(&buf, level_of(text, len),
                                          (uint32_t)(esp_timer_get_time() / 1000),
                                          len);
    if (frame_len > 0) {
        /* Never wait. A full queue means the PC is not draining, and a log is
         * not worth stalling the task that produced it. */
        (void)tx_send(&buf, frame_len, 0);
    }

    return n;
}

/* ── Serving ────────────────────────────────────────────────────────────── */

/* Answers one decoded frame. Replies to requests; ignores anything else,
 * since a reply or a log arriving here is the PC echoing, not asking. */
static void serve(const rpc_buf_t *frame, size_t len)
{
    static rpc_buf_t reply;

    rpc_view_t v;
    if (!rpc_frame_open(frame, len, &v) || v.type != RPC_FRAME_REQ) {
        return;
    }

    const rpc_req_hdr_t *req = v.hdr;

    /* Any request that parsed is the PC proving it is still there. */
    watchdog_feed();

    /*
     * The handler writes its return values straight into the reply frame, so
     * what comes back is only how much of it to send. No length can exceed what
     * a frame holds: rpc_register refused the table otherwise, which is why
     * there is no "it did not fit" path left to write.
     */
    size_t       ret_len = 0;
    rpc_status_t status  = rpc_dispatch(req->ns, req->method,
                                        v.payload, v.payload_len,
                                        rpc_payload(&reply), &ret_len);

    size_t reply_len = rpc_frame_seal_rep(&reply, req->id, status, ret_len);
    if (reply_len > 0) {
        (void)tx_send(&reply, reply_len, pdMS_TO_TICKS(100));
    }
}

/*
 * Bytes arrive in whatever sizes USB felt like. A frame is what lies between
 * two zeros, so this accumulates until one shows up and hands the run over.
 *
 * An overlong run is discarded, and so is everything after it up to the next
 * zero. That is the property COBS was chosen for: the resynchronisation point
 * is defined, not guessed, and is at most one frame away.
 */
static void rx_task(void *arg)
{
    (void)arg;

    static uint8_t chunk[RPC_USB_CHUNK];
    static uint8_t run[RPC_ENCODED_MAX];

    /* The union rather than a byte array, because serve() reads the header
     * through its own type and a byte array is aligned for nothing. */
    static rpc_buf_t decoded;

    size_t run_len = 0;
    bool   overrun = false;

    for (;;) {
        /*
         * A bounded wait rather than portMAX_DELAY, because silence is the
         * thing the watchdog is watching for and a task blocked forever cannot
         * notice it. This task owns the devices, so the check belongs here
         * rather than in a timer callback that would race it.
         */
        int got = usb_serial_jtag_read_bytes(chunk, sizeof(chunk),
                                             pdMS_TO_TICKS(WATCHDOG_TICK_MS));

        watchdog_tick(usb_serial_jtag_is_connected());

        if (got <= 0) {
            continue;
        }

        for (int i = 0; i < got; i++) {
            if (chunk[i] != 0x00) {
                if (run_len < sizeof(run)) {
                    run[run_len++] = chunk[i];
                } else {
                    overrun = true;
                }
                continue;
            }

            if (!overrun && run_len > 0) {
                size_t len = cobs_decode(run, run_len, decoded.bytes,
                                         sizeof(decoded.bytes));
                if (len > 0) {
                    serve(&decoded, len);
                }
            }

            run_len = 0;
            overrun = false;
        }
    }
}

/* ── Start ──────────────────────────────────────────────────────────────── */

esp_err_t rpc_link_start(void)
{
    if (s_started) {
        return ESP_ERR_INVALID_STATE;
    }

    usb_serial_jtag_driver_config_t cfg = {
        .rx_buffer_size = 1024,
        .tx_buffer_size = 2048,
    };

    esp_err_t err = usb_serial_jtag_driver_install(&cfg);
    if (err != ESP_OK) {
        return err;
    }

    s_txq = xQueueCreate(RPC_TXQ_DEPTH, sizeof(tx_frame_t));
    if (s_txq == NULL) {
        return ESP_ERR_NO_MEM;
    }

    if (xTaskCreate(tx_task, "rpc_tx", 3072, NULL, 5, NULL) != pdPASS ||
        xTaskCreate(rx_task, "rpc_rx", 4096, NULL, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    /*
     * Last, deliberately. Anything that failed above still had a console to
     * report it on, and stdout stops being a place logs go only once there is
     * a link able to carry them.
     */
    esp_log_set_vprintf(log_to_link);
    s_started = true;

    return ESP_OK;
}
