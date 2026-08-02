#include "backends.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/pulse_cnt.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "sdkconfig.h"

#define STEPGEN_RESOLUTION_HZ 1000000U
#define STEPGEN_PULSE_TICKS   2U
#define STEPGEN_TICK_NS       (1000000000U / STEPGEN_RESOLUTION_HZ)
#define STEPGEN_MAX_PPS       ((uint32_t)CONFIG_STEF_STEPGEN_MAX_PPS)
#define STEPGEN_MIN_PPS       ((STEPGEN_RESOLUTION_HZ / 32767U) + 1U)
#define STEPGEN_MEM_SYMBOLS   48U
#define STEPGEN_PCNT_HIGH     10000
#define STEPGEN_PCNT_LOW      (-1)

static const char *TAG = "stepgen";

typedef struct {
    rmt_channel_handle_t chan;
    rmt_encoder_handle_t encoder;
    pcnt_unit_handle_t   pcnt;

    uint32_t pulses;
    uint32_t pullin_pps;
    uint64_t pullin_sq;
    uint32_t accel_pps_s;

    volatile uint32_t target_pps;
    volatile uint32_t cur_pps;
    volatile bool     stopping;
    volatile bool     running;

    uint64_t v_sq;
    uint32_t v;
    uint32_t rem;
} stepgen_t;

static stepgen_t         s_gen[BACKENDS_MAX_DRIVERS];
static tmc2209_stepgen_t s_backend[BACKENDS_MAX_DRIVERS];
static bool              s_present[BACKENDS_MAX_DRIVERS];
static bool              s_ready;

/* ── The ramp ───────────────────────────────────────────────────────────── */

static uint64_t squared(uint32_t rate)
{
    return (uint64_t)rate * (uint64_t)rate;
}

/*
 * v dv/dn = a with n in pulses, so the square of the rate moves by a constant
 * 2a every pulse and the square root is the only thing that costs anything.
 * Seeded with the previous rate, which is within one increment, so it lands in
 * the first iteration and the other two are there to make that a fact rather
 * than an expectation.
 */
static uint32_t rate_from_square(uint64_t v_sq, uint32_t seed)
{
    uint32_t x = seed ? seed : 1U;

    for (int i = 0; i < 3; i++) {
        x = (uint32_t)((x + (v_sq / x)) / 2U);
        if (x == 0U) {
            x = 1U;
        }
    }

    return x;
}

/*
 * Where the down ramp begins is not decided in advance. Every pulse asks
 * whether the pulses still owed are as few as the pulses it would take to
 * reach the pull-in rate from here, and brakes the moment they are. A run too
 * short to finish accelerating starts braking before it ever reaches cruise,
 * which is the triangle, and a rate retargeted mid-flight moves the braking
 * point with it for free.
 */
static void advance_rate(stepgen_t *g, uint32_t index)
{
    const uint64_t step = 2ULL * (uint64_t)g->accel_pps_s;
    if (step == 0U) {
        return;
    }

    uint64_t goal_sq;
    if (g->stopping) {
        goal_sq = g->pullin_sq;
    } else if (g->pulses != 0U) {
        const uint64_t excess = (g->v_sq > g->pullin_sq) ? (g->v_sq - g->pullin_sq) : 0U;
        const uint64_t brake  = excess / step;
        goal_sq = ((uint64_t)(g->pulses - index) <= brake) ? g->pullin_sq
                                                          : squared(g->target_pps);
    } else {
        goal_sq = squared(g->target_pps);
    }

    if (g->v_sq < goal_sq) {
        g->v_sq += step;
        if (g->v_sq > goal_sq) {
            g->v_sq = goal_sq;
        }
    } else if (g->v_sq > goal_sq) {
        g->v_sq = (g->v_sq > goal_sq + step) ? (g->v_sq - step) : goal_sq;
    }

    g->v = rate_from_square(g->v_sq, g->v);
}

/*
 * One symbol is one pulse, which is what makes the count exact: the hardware
 * cannot emit a symbol that was never encoded. The period divides unevenly at
 * most rates, so the remainder carries into the next pulse rather than being
 * dropped. Each period is then off by at most one tick and the mean rate is
 * the rate asked for, which is the difference between jitter and drift.
 */
static size_t encode_run(const void *data, size_t data_size,
                         size_t symbols_written, size_t symbols_free,
                         rmt_symbol_word_t *symbols, bool *done, void *arg)
{
    (void)data;
    (void)data_size;

    stepgen_t *g = (stepgen_t *)arg;

    size_t budget = symbols_free;
    if (g->pulses != 0U) {
        const size_t owed = g->pulses - symbols_written;
        if (budget > owed) {
            budget = owed;
        }
    }

    size_t   n       = 0;
    bool     braked  = false;

    while (n < budget) {
        advance_rate(g, (uint32_t)(symbols_written + n));

        const uint32_t num    = STEPGEN_RESOLUTION_HZ + g->rem;
        uint32_t       period = num / g->v;
        g->rem = num - (period * g->v);

        if (period <= STEPGEN_PULSE_TICKS) {
            period = STEPGEN_PULSE_TICKS + 1U;
        }

        symbols[n].level0    = 1;
        symbols[n].duration0 = STEPGEN_PULSE_TICKS;
        symbols[n].level1    = 0;
        symbols[n].duration1 = period - STEPGEN_PULSE_TICKS;
        n++;

        if (g->stopping && g->v <= g->pullin_pps) {
            braked = true;
            break;
        }
    }

    g->cur_pps = g->v;

    *done = braked || (g->pulses != 0U && (symbols_written + n) >= g->pulses);
    return n;
}

static bool on_run_done(rmt_channel_handle_t chan,
                        const rmt_tx_done_event_data_t *edata, void *arg)
{
    (void)chan;
    (void)edata;

    stepgen_t *g = (stepgen_t *)arg;
    g->running = false;
    g->cur_pps = 0U;

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

    g->pulses      = plan->pulses;
    g->pullin_pps  = plan->pullin_pps;
    g->pullin_sq   = squared(plan->pullin_pps);
    g->accel_pps_s = plan->accel_pps_s;
    g->target_pps  = plan->cruise_pps;
    g->stopping    = false;
    g->v           = plan->pullin_pps;
    g->v_sq        = g->pullin_sq;
    g->rem         = 0U;
    g->cur_pps     = plan->pullin_pps;
    g->running     = true;

    const rmt_transmit_config_t cfg = {
        .loop_count = 0,
        .flags = { .eot_level = 0, .queue_nonblocking = true },
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
    if (cruise_pps < STEPGEN_MIN_PPS || cruise_pps > STEPGEN_MAX_PPS) {
        return -1;
    }

    g->target_pps = cruise_pps;
    return 0;
}

/*
 * The ramped form only asks: the encoder is already a pipeline of pulses the
 * hardware has not emitted yet, so the run ends when those are out and not
 * when the request lands. The immediate form cuts mid-symbol, which is why the
 * count is not kept here.
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

    const bool running = g->running;
    const uint32_t rate = g->cur_pps;

    int count = 0;
    if (pcnt_unit_get_count(g->pcnt, &count) != ESP_OK) {
        return -1;
    }

    out->emitted  = (count > 0) ? (uint32_t)count : 0U;
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
        .flags = { .accum_count = 1 },
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
        .flags = { .virt_level_io_level = 1 },
    };

    pcnt_channel_handle_t chan = NULL;
    err = pcnt_new_channel(g->pcnt, &chan_cfg, &chan);
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
        .flags = { .io_loop_back = 1, .init_level = 0 },
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
    err = rmt_tx_register_event_callbacks(g->chan, &cbs, g);
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
            /* The chip has four of each and the bench image spends one channel
               on the status LED, so running out is a real outcome and not a
               theoretical one. Say which resource, because the fix differs. */
            ESP_LOGE(TAG, "%s step on gpio%d: %s", d->name, d->step,
                     esp_err_to_name(err));
            return err;
        }

        s_backend[i] = (tmc2209_stepgen_t){
            .run          = gen_run,
            .retarget     = gen_retarget,
            .halt         = gen_halt,
            .state        = gen_state,
            .ctx          = &s_gen[i],
            .max_pps      = STEPGEN_MAX_PPS,
            .min_pulse_ns = STEPGEN_PULSE_TICKS * STEPGEN_TICK_NS,
        };
        s_present[i] = true;

        ESP_LOGI(TAG, "%s step on gpio%d, %u..%u pps", d->name, d->step,
                 (unsigned)STEPGEN_MIN_PPS, (unsigned)STEPGEN_MAX_PPS);
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
