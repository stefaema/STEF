/*
 * stepgen.c: one RMT symbol per pulse, and a counter watching the pad.
 *
 * One symbol per pulse is what makes a bounded run exact: the hardware cannot
 * emit a symbol the encoder never wrote. The count comes off PCNT rather than
 * off the encoder because the encoder runs ahead of the pad, so after a cut
 * mid-train its number is pulses encoded and PCNT's is pulses emitted.
 *
 * What rate a symbol carries is ramp.c's answer, and it is asked once per chunk
 * of pulses rather than once per pulse. This file only shapes the symbol.
 */

#include "backends.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/pulse_cnt.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "ramp.h"
#include "sdkconfig.h"

#define STEPGEN_RESOLUTION_HZ 1000000U
#define STEPGEN_TICK_NS       (1000000000U / STEPGEN_RESOLUTION_HZ)

/* A period is split evenly between the two halves of its symbol rather than
   spent on the narrowest pulse the part will accept. The datasheet's floor is
   around 100 ns and a fixed 2 tick pulse cleared it twenty times over, but a
   narrow pulse is the first thing a long jumper wire and a poor ground return
   take apart, and every reference driver for this part sends a square wave. So
   the margin goes where it costs nothing: at the top rate the half is still a
   microsecond, and at the bottom both halves carry the 15 bit duration field
   instead of one, which is what doubles the slow end. */
#define STEPGEN_DURATION_MAX 32767U
#define STEPGEN_MIN_PERIOD   2U
#define STEPGEN_MAX_PPS      ((uint32_t)CONFIG_STEF_STEPGEN_MAX_PPS)
#define STEPGEN_MIN_PPS      ((STEPGEN_RESOLUTION_HZ / (2U * STEPGEN_DURATION_MAX)) + 1U)
#define STEPGEN_MEM_SYMBOLS  48U
#define STEPGEN_PCNT_HIGH    10000
#define STEPGEN_PCNT_LOW     (-1)

static const char *TAG = "stepgen";

typedef struct {
    rmt_channel_handle_t chan;
    rmt_encoder_handle_t encoder;
    pcnt_unit_handle_t   pcnt;

    /* Owned by the encoder, which runs in the RMT interrupt. */
    ramp_t ramp;

    /* Written by the commanding task, read by the encoder. 32-bit and aligned,
       so each load is whole even though the pair is not. */
    volatile uint32_t target_pps;
    volatile uint32_t cur_pps;
    volatile bool     stopping;
    volatile bool     running;
} stepgen_t;

static stepgen_t         s_gen[BACKENDS_MAX_DRIVERS];
static tmc2209_stepgen_t s_backend[BACKENDS_MAX_DRIVERS];
static bool              s_present[BACKENDS_MAX_DRIVERS];
static bool              s_ready;

/* ── The symbols ────────────────────────────────────────────────────────── */

static size_t encode_run(const void *data, size_t data_size, size_t symbols_written,
                         size_t symbols_free, rmt_symbol_word_t *symbols, bool *done, void *arg)
{
    (void)data;
    (void)data_size;

    stepgen_t *g = (stepgen_t *)arg;

    size_t budget = symbols_free;
    if (g->ramp.pulses != 0U) {
        const size_t owed = g->ramp.pulses - symbols_written;
        if (budget > owed) {
            budget = owed;
        }
    }

    size_t n     = 0;
    bool   ended = false;

    while (n < budget && !ended) {
        ramp_chunk_t chunk;
        ramp_next(&g->ramp, (uint32_t)(symbols_written + n), (uint32_t)(budget - n), g->target_pps,
                  g->stopping, &chunk);

        for (uint32_t i = 0; i < chunk.count; i++) {
            const uint32_t period = ramp_period(&g->ramp, &chunk);
            const uint32_t high   = period / 2U;

            symbols[n].level0    = 1;
            symbols[n].duration0 = high;
            symbols[n].level1    = 0;
            symbols[n].duration1 = period - high;
            n++;
        }

        g->cur_pps = chunk.rate_pps;
        ended      = chunk.last;
    }

    *done = ended || (g->ramp.pulses != 0U && (symbols_written + n) >= g->ramp.pulses);
    return n;
}

static bool on_run_done(rmt_channel_handle_t chan, const rmt_tx_done_event_data_t *edata, void *arg)
{
    (void)chan;
    (void)edata;

    stepgen_t *g = (stepgen_t *)arg;
    g->running   = false;
    g->cur_pps   = 0U;

    return false;
}

/* ── The contract ───────────────────────────────────────────────────────── */

static int gen_run(void *ctx, const tmc2209_run_plan_t *plan)
{
    stepgen_t *g = (stepgen_t *)ctx;

    if (g->running) {
        return -1;
    }
    /* Below this the low half of a symbol outruns the 15-bit duration field,
       and a rate quietly served as some other rate is what this backend
       exists to make impossible. */
    if (plan->pullin_pps < STEPGEN_MIN_PPS || plan->cruise_pps < STEPGEN_MIN_PPS) {
        ESP_LOGE(TAG, "rate below %u pps", (unsigned)STEPGEN_MIN_PPS);
        return -1;
    }
    if (pcnt_unit_clear_count(g->pcnt) != ESP_OK) {
        return -1;
    }

    const ramp_plan_t rp = {
        .pulses           = plan->pulses,
        .pullin_pps       = plan->pullin_pps,
        .accel_pps_s      = plan->accel_pps_s,
        .resolution_hz    = STEPGEN_RESOLUTION_HZ,
        .min_period_ticks = STEPGEN_MIN_PERIOD,
    };
    ramp_begin(&g->ramp, &rp);

    g->target_pps = plan->cruise_pps;
    g->stopping   = false;
    g->cur_pps    = plan->pullin_pps;
    g->running    = true;

    const rmt_transmit_config_t cfg = {
        .loop_count = 0,
        .flags      = { .eot_level = 0, .queue_nonblocking = true },
    };

    if (rmt_transmit(g->chan, g->encoder, g, sizeof *g, &cfg) != ESP_OK) {
        g->running = false;
        g->cur_pps = 0U;
        return -1;
    }

    return 0;
}

static int gen_retarget(void *ctx, uint32_t cruise_pps)
{
    stepgen_t *g = (stepgen_t *)ctx;

    if (!g->running) {
        return -1;
    }
    /* A run already braking has one destination left, and it is not this one. */
    if (g->stopping) {
        return -1;
    }
    if (cruise_pps < STEPGEN_MIN_PPS || cruise_pps > STEPGEN_MAX_PPS) {
        return -1;
    }

    g->target_pps = cruise_pps;
    return 0;
}

/*
 * The ramped form only asks: the encoder is already a pipeline of pulses the
 * hardware has not emitted yet, so the run ends when those are out and not
 * when the request lands. A bounded run whose tail is already encoded ignores
 * it, which is right, since the brake it would ask for is in that tail. The
 * immediate form cuts mid-symbol, which is why the count is not kept here.
 */
static int gen_halt(void *ctx, bool immediate)
{
    stepgen_t *g = (stepgen_t *)ctx;

    if (!g->running) {
        return 0;
    }
    if (!immediate) {
        g->stopping = true;
        return 0;
    }
    if (rmt_disable(g->chan) != ESP_OK) {
        return -1;
    }

    g->running = false;
    g->cur_pps = 0U;

    return (rmt_enable(g->chan) == ESP_OK) ? 0 : -1;
}

/*
 * The count comes off the counter unit, which watched the pin rather than the
 * encoder, so it survives a train cut between two edges. Whether a run is in
 * flight is read first: reported running against a count that has since become
 * final only costs one more poll, while the other order reports a finished run
 * short by whatever came out in between.
 */
static int gen_state(void *ctx, tmc2209_run_state_t *out)
{
    stepgen_t *g = (stepgen_t *)ctx;

    const bool     running = g->running;
    const uint32_t rate    = g->cur_pps;

    int count = 0;
    if (pcnt_unit_get_count(g->pcnt, &count) != ESP_OK) {
        return -1;
    }

    /* The unit only ever counts up, so this is a reinterpretation and not a
       clamp: an unbounded run past 2^31 pulses keeps counting, and wraps. */
    out->emitted  = (uint32_t)count;
    out->rate_pps = rate;
    out->running  = running;

    return 0;
}

/* ── Bring-up ───────────────────────────────────────────────────────────── */

/*
 * The counter taps the same pad the channel drives, through the loopback the
 * channel enables, so nothing about this needs a wire the board does not
 * already have. It is created after the channel for that reason.
 */
static esp_err_t configure_counter(stepgen_t *g, int step_pin)
{
    const pcnt_unit_config_t unit_cfg = {
        .low_limit  = STEPGEN_PCNT_LOW,
        .high_limit = STEPGEN_PCNT_HIGH,
        .flags      = { .accum_count = 1 },
    };

    esp_err_t err = pcnt_new_unit(&unit_cfg, &g->pcnt);
    if (err != ESP_OK) {
        return err;
    }

    /* The accumulation the flag above promises happens on reaching a limit,
       and a limit is only noticed if it is watched. Without this the count
       wraps at 10000 pulses, which is a third of a turn. */
    err = pcnt_unit_add_watch_point(g->pcnt, STEPGEN_PCNT_HIGH);
    if (err != ESP_OK) {
        return err;
    }

    const pcnt_chan_config_t chan_cfg = {
        .edge_gpio_num  = step_pin,
        .level_gpio_num = -1,
        .flags          = { .virt_level_io_level = 1 },
    };

    pcnt_channel_handle_t chan = NULL;
    err                        = pcnt_new_channel(g->pcnt, &chan_cfg, &chan);
    if (err != ESP_OK) {
        return err;
    }

    err = pcnt_channel_set_edge_action(chan, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                       PCNT_CHANNEL_EDGE_ACTION_HOLD);
    if (err != ESP_OK) {
        return err;
    }

    err = pcnt_channel_set_level_action(chan, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                        PCNT_CHANNEL_LEVEL_ACTION_KEEP);
    if (err != ESP_OK) {
        return err;
    }

    err = pcnt_unit_enable(g->pcnt);
    if (err != ESP_OK) {
        return err;
    }

    err = pcnt_unit_clear_count(g->pcnt);
    if (err != ESP_OK) {
        return err;
    }

    return pcnt_unit_start(g->pcnt);
}

static esp_err_t configure_channel(stepgen_t *g, int step_pin)
{
    const rmt_tx_channel_config_t chan_cfg = {
        .gpio_num          = (gpio_num_t)step_pin,
        .clk_src           = RMT_CLK_SRC_DEFAULT,
        .resolution_hz     = STEPGEN_RESOLUTION_HZ,
        .mem_block_symbols = STEPGEN_MEM_SYMBOLS,
        .trans_queue_depth = 1,
        .flags             = { .io_loop_back = 1, .init_level = 0 },
    };

    esp_err_t err = rmt_new_tx_channel(&chan_cfg, &g->chan);
    if (err != ESP_OK) {
        return err;
    }

    const rmt_simple_encoder_config_t enc_cfg = {
        .callback       = encode_run,
        .arg            = g,
        .min_chunk_size = 1,
    };

    err = rmt_new_simple_encoder(&enc_cfg, &g->encoder);
    if (err != ESP_OK) {
        return err;
    }

    const rmt_tx_event_callbacks_t cbs = { .on_trans_done = on_run_done };
    err                                = rmt_tx_register_event_callbacks(g->chan, &cbs, g);
    if (err != ESP_OK) {
        return err;
    }

    return rmt_enable(g->chan);
}

esp_err_t backends_stepgen_init(const board_t *board)
{
    if (s_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    if (board == NULL || board->n_drivers > BACKENDS_MAX_DRIVERS) {
        return ESP_ERR_INVALID_ARG;
    }

    for (size_t i = 0; i < board->n_drivers; i++) {
        const board_driver_t *d = &board->drivers[i];

        /* A board that does not wire STEP gets no pulse source, and the
           library refuses every motion call on it by itself. */
        if (d->step == BOARD_PIN_NONE) {
            continue;
        }

        esp_err_t err = configure_channel(&s_gen[i], d->step);
        if (err == ESP_OK) {
            err = configure_counter(&s_gen[i], d->step);
        }

        if (err != ESP_OK) {
            /* Four RMT channels and four PCNT units on this part, one of each
               per driver that pulses. Say which resource, because the fix differs. */
            ESP_LOGE(TAG, "%s step on gpio%d: %s", d->name, d->step, esp_err_to_name(err));
            return err;
        }

        s_backend[i] = (tmc2209_stepgen_t){
            .run          = gen_run,
            .retarget     = gen_retarget,
            .halt         = gen_halt,
            .state        = gen_state,
            .ctx          = &s_gen[i],
            .max_pps      = STEPGEN_MAX_PPS,
            /* Half of the shortest period this backend will encode. */
            .min_pulse_ns = (STEPGEN_MIN_PERIOD / 2U) * STEPGEN_TICK_NS,
        };
        s_present[i] = true;

        ESP_LOGI(TAG, "%s step on gpio%d, %u..%u pps", d->name, d->step, (unsigned)STEPGEN_MIN_PPS,
                 (unsigned)STEPGEN_MAX_PPS);
    }

    s_ready = true;
    return ESP_OK;
}

const tmc2209_stepgen_t *backends_stepgen(size_t i)
{
    if (!s_ready || i >= BACKENDS_MAX_DRIVERS || !s_present[i]) {
        return NULL;
    }
    return &s_backend[i];
}
