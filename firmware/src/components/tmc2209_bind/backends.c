#include "backends.h"

#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#define UART_RX_BUF 256

static const char *TAG = "backends";

static bool           s_ready;
static int            s_uart_num;
static tmc2209_uart_t s_uart_backend;

/* One lines backend per driver, each pointing at its own row of the table. */
static tmc2209_lines_t       s_lines[BACKENDS_MAX_DRIVERS];
static const board_driver_t *s_wiring[BACKENDS_MAX_DRIVERS];

/* ── UART ───────────────────────────────────────────────────────────── */

/*
 * The backend reports bytes moved, never meaning.
 */

static int uart_tx(void *ctx, const uint8_t *buf, size_t len, uint32_t timeout_ms)
{
    (void)ctx;

    int sent = uart_write_bytes(s_uart_num, buf, len);
    if (sent < 0) {
        return sent;
    }

    /* Wait for the last bit to leave. */
    if (uart_wait_tx_done(s_uart_num, pdMS_TO_TICKS(timeout_ms)) != ESP_OK) {
        return -1;
    }

    return sent;
}

static int uart_rx(void *ctx, uint8_t *buf, size_t len, uint32_t timeout_ms)
{
    (void)ctx;
    return uart_read_bytes(s_uart_num, buf, (uint32_t)len, pdMS_TO_TICKS(timeout_ms));
}

static void uart_purge_rx(void *ctx)
{
    (void)ctx;

    uint8_t scrap[32];
    for (int i = 0; i < 16; i++) {
        if (uart_read_bytes(s_uart_num, scrap, sizeof scrap, 0) <= 0) {
            return;
        }
    }
}

#if CONFIG_STEF_TMC_UART_TRACE
#define TRACE_MAX_BYTES 32

static void uart_trace(void *ctx, bool outbound, const uint8_t *buf, size_t len)
{
    (void)ctx;

    char   hex[(3 * TRACE_MAX_BYTES) + 1];
    size_t shown = (len < TRACE_MAX_BYTES) ? len : TRACE_MAX_BYTES;
    size_t n     = 0;

    for (size_t i = 0; i < shown; i++) {
        n += (size_t)snprintf(&hex[n], sizeof(hex) - n, "%02X ", buf[i]);
    }
    hex[n] = '\0';

    ESP_LOGI(TAG, "%s %u: %s", outbound ? "tx" : "rx", (unsigned)len, (len > 0) ? hex : "(-)");
}
#endif

/* ── The pins ───────────────────────────────────────────────────────────── */

/* Which GPIO carries a role on this driver, or BOARD_PIN_NONE. */
static int pin_of(const board_driver_t *d, tmc2209_line_t line)
{
    switch (line) {
    /* clang-format off */
    case TMC2209_LINE_ENN:  return d->enn;
    case TMC2209_LINE_DIR:  return d->dir;
    case TMC2209_LINE_STEP: return d->step;
    case TMC2209_LINE_DIAG: return d->diag;
    default:                return BOARD_PIN_NONE;
    /* clang-format on */
    }
}

static int lines_read(void *ctx, tmc2209_line_t line)
{
    const board_driver_t *d = ctx;

    int pin = pin_of(d, line);
    if (pin == BOARD_PIN_NONE) {
        return -1;
    }

    /* Outputs are configured INPUT_OUTPUT, so this reads back the level being driven */
    return gpio_get_level((gpio_num_t)pin);
}

static int lines_write(void *ctx, tmc2209_line_t line, bool level)
{
    const board_driver_t *d = ctx;

    int pin = pin_of(d, line);
    if (pin == BOARD_PIN_NONE) {
        return -1;
    }

    return gpio_set_level((gpio_num_t)pin, level ? 1U : 0U) == ESP_OK ? 0 : -1;
}

/* The mask the library checks before it calls a write or read. */
static uint8_t wired_mask(const board_driver_t *d)
{
    uint8_t wired = 0;

    if (d->enn != BOARD_PIN_NONE) {
        wired |= TMC2209_LINE_BIT(TMC2209_LINE_ENN);
    }
    if (d->dir != BOARD_PIN_NONE) {
        wired |= TMC2209_LINE_BIT(TMC2209_LINE_DIR);
    }
    if (d->step != BOARD_PIN_NONE) {
        wired |= TMC2209_LINE_BIT(TMC2209_LINE_STEP);
    }
    if (d->diag != BOARD_PIN_NONE) {
        wired |= TMC2209_LINE_BIT(TMC2209_LINE_DIAG);
    }

    return wired;
}

/* The resting level is set before the pin becomes an output.*/
static esp_err_t configure_output(int pin, uint32_t resting)
{
    esp_err_t err = gpio_set_level((gpio_num_t)pin, resting);
    if (err != ESP_OK) {
        return err;
    }

    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << (unsigned)pin,
        .mode         = GPIO_MODE_INPUT_OUTPUT, /* so a read means the driven level */
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };

    err = gpio_config(&cfg);
    if (err != ESP_OK) {
        return err;
    }

    return gpio_set_level((gpio_num_t)pin, resting);
}

static esp_err_t configure_input(int pin)
{
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << (unsigned)pin,
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE, /* DIAG is open-drain */
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };

    return gpio_config(&cfg);
}

static esp_err_t configure_driver_pins(const board_driver_t *d)
{
    esp_err_t err = ESP_OK;

    /* ENN is active low. */
    if (d->enn != BOARD_PIN_NONE) {
        err = configure_output(d->enn, 1);
    }
    if (err == ESP_OK && d->dir != BOARD_PIN_NONE) {
        err = configure_output(d->dir, 0);
    }
    if (err == ESP_OK && d->step != BOARD_PIN_NONE) {
        err = configure_output(d->step, 0);
    }
    if (err == ESP_OK && d->diag != BOARD_PIN_NONE) {
        err = configure_input(d->diag);
    }

    return err;
}

/* ── Bring-up ───────────────────────────────────────────────────────────── */

static esp_err_t configure_uart(const board_t *board)
{
    uart_config_t cfg = {
        .baud_rate  = (int)board->baud,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err = uart_driver_install(board->uart_num, UART_RX_BUF, 0, 0, NULL, 0);
    if (err != ESP_OK) {
        return err;
    }

    err = uart_param_config(board->uart_num, &cfg);
    if (err != ESP_OK) {
        return err;
    }

    return uart_set_pin(board->uart_num, board->uart_tx, board->uart_rx, UART_PIN_NO_CHANGE,
                        UART_PIN_NO_CHANGE);
}

esp_err_t backends_init(const board_t *board)
{
    if (s_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    if (board == NULL || board->n_drivers == 0 || board->n_drivers > BACKENDS_MAX_DRIVERS) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = configure_uart(board);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "uart%d: %s", board->uart_num, esp_err_to_name(err));
        return err;
    }

    s_uart_num = board->uart_num;

    s_uart_backend = (tmc2209_uart_t){
        .tx       = uart_tx,
        .rx       = uart_rx,
        .purge_rx = uart_purge_rx,
#if CONFIG_STEF_TMC_UART_TRACE
        .trace = uart_trace,
#endif
        .ctx    = NULL,
        /* TX and RX meet at PDN_UART, so every byte we send comes back. */
        .echoes = true,

        /* Library policy rather than peripheral fact, and the board table's to
           choose: how long a driver gets to answer, and how many times a
           mangled datagram is worth sending again. */
        .timeout_ms = board->timeout_ms,
        .retries    = board->retries,
    };

    for (size_t i = 0; i < board->n_drivers; i++) {
        const board_driver_t *d = &board->drivers[i];

        err = configure_driver_pins(d);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "%s pins: %s", d->name, esp_err_to_name(err));
            return err;
        }

        s_wiring[i] = d;
        s_lines[i]  = (tmc2209_lines_t){
             .read  = lines_read,
             .write = lines_write,
             .ctx   = (void *)d,
             .wired = wired_mask(d),
        };
    }

    /* After the pins, because both peripherals behind a pulse source attach to
       a pad that has to already exist and already rest low. */
    err = backends_stepgen_init(board);
    if (err != ESP_OK) {
        return err;
    }

    s_ready = true;
    return ESP_OK;
}

const tmc2209_uart_t *backends_uart(void)
{
    return s_ready ? &s_uart_backend : NULL;
}

const tmc2209_lines_t *backends_lines(size_t i)
{
    if (!s_ready || i >= BACKENDS_MAX_DRIVERS || s_wiring[i] == NULL) {
        return NULL;
    }
    return &s_lines[i];
}
