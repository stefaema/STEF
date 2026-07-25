#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <inttypes.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/rmt_tx.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_system.h"
#include "led_strip_encoder.h"

#define WS2812_GPIO CONFIG_STEF_WS2812_GPIO
#define WS2812_RESOLUTION_HZ 10000000 // 10MHz, 1 tick = 0.1us, required by the WS2812 bit timing

/*
 * Each self-test is a single command a human (today, over the serial
 * console) or the PC-side GUI (later, over the same UART) can trigger
 * independently, so a failure points at one thing instead of "something's
 * wrong with the ESP32". See firmware/docs/roadmap.md for the layer this
 * fits into.
 */
typedef struct {
    char cmd;
    const char *name;
    esp_err_t (*run)(void);
} selftest_t;

static void print_chip_identity(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);

    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    printf("Chip: %s, %d core(s), rev v%d.%d\n",
           CONFIG_IDF_TARGET, info.cores,
           info.revision / 100, info.revision % 100);
    printf("Features: WiFi=%s BT=%s BLE=%s\n",
           (info.features & CHIP_FEATURE_WIFI_BGN) ? "yes" : "no",
           (info.features & CHIP_FEATURE_BT) ? "yes" : "no",
           (info.features & CHIP_FEATURE_BLE) ? "yes" : "no");
    printf("Flash: %" PRIu32 " MB (as reported by the chip, not verified against a real read/write yet)\n",
           flash_size / (1024 * 1024));
}

static void print_reset_reason(void)
{
    const char *name = "UNKNOWN";
    switch (esp_reset_reason()) {
        case ESP_RST_POWERON:  name = "POWERON"; break;
        case ESP_RST_BROWNOUT: name = "BROWNOUT (check the power supply)"; break;
        case ESP_RST_PANIC:    name = "PANIC (firmware crash)"; break;
        case ESP_RST_TASK_WDT: name = "TASK WATCHDOG"; break;
        case ESP_RST_SW:       name = "SOFTWARE RESET"; break;
        default: break;
    }
    printf("Last reset reason: %s\n", name);
}

static rmt_channel_handle_t ws2812_chan = NULL;
static rmt_encoder_handle_t ws2812_encoder = NULL;

/* Created on first use and left enabled, rather than torn down after every
 * self-test run, since re-creating the RMT channel/encoder on each blink
 * would add per-call setup cost for no benefit here. */
static esp_err_t ws2812_ensure_init(void)
{
    if (ws2812_chan != NULL) {
        return ESP_OK;
    }

    rmt_tx_channel_config_t tx_chan_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = WS2812_GPIO,
        .mem_block_symbols = 64,
        .resolution_hz = WS2812_RESOLUTION_HZ,
        .trans_queue_depth = 4,
    };
    esp_err_t err = rmt_new_tx_channel(&tx_chan_config, &ws2812_chan);
    if (err != ESP_OK) {
        return err;
    }

    led_strip_encoder_config_t encoder_config = {
        .resolution = WS2812_RESOLUTION_HZ,
    };
    err = rmt_new_led_strip_encoder(&encoder_config, &ws2812_encoder);
    if (err != ESP_OK) {
        return err;
    }

    return rmt_enable(ws2812_chan);
}

static esp_err_t ws2812_set(uint8_t r, uint8_t g, uint8_t b)
{
    esp_err_t err = ws2812_ensure_init();
    if (err != ESP_OK) {
        return err;
    }

    uint8_t pixel[3] = { g, r, b }; // WS2812 wire order is G, R, B
    rmt_transmit_config_t tx_config = { .loop_count = 0 };
    err = rmt_transmit(ws2812_chan, ws2812_encoder, pixel, sizeof(pixel), &tx_config);
    if (err != ESP_OK) {
        return err;
    }
    return rmt_tx_wait_all_done(ws2812_chan, pdMS_TO_TICKS(100));
}

static esp_err_t test_led_blink(void)
{
    printf("Blinking the onboard WS2812 (GPIO%d) three times...\n", WS2812_GPIO);
    for (int i = 0; i < 3; i++) {
        esp_err_t err = ws2812_set(255, 255, 255);
        if (err != ESP_OK) {
            printf("RMT transmit failed: %s\n", esp_err_to_name(err));
            return ESP_FAIL;
        }
        vTaskDelay(pdMS_TO_TICKS(200));
        ws2812_set(0, 0, 0);
        vTaskDelay(pdMS_TO_TICKS(200));
    }

    printf("Did the LED blink? [y/n]: ");
    fflush(stdout);

    char line[8] = { 0 };
    if (fgets(line, sizeof(line), stdin) == NULL) {
        return ESP_FAIL;
    }
    return (line[0] == 'y' || line[0] == 'Y') ? ESP_OK : ESP_FAIL;
}

static esp_err_t test_wifi_scan(void)
{
    printf("[SKIP] wifi-scan not implemented yet.\n");
    return ESP_ERR_NOT_SUPPORTED;
}

static esp_err_t test_gpio_loopback(void)
{
    printf("[SKIP] gpio-loopback not implemented yet "
           "(needs a jumper between a designated output and a probe pin).\n");
    return ESP_ERR_NOT_SUPPORTED;
}

static const selftest_t tests[] = {
    { 'l', "led-blink (visual confirm)", test_led_blink },
    { 'w', "wifi-scan",                  test_wifi_scan },
    { 'g', "gpio-loopback",              test_gpio_loopback },
};

static void print_menu(void)
{
    printf("\nSTEF ESP32 self-test - commands:\n");
    for (size_t i = 0; i < sizeof(tests) / sizeof(tests[0]); i++) {
        printf("  %c - %s\n", tests[i].cmd, tests[i].name);
    }
    printf("> ");
    fflush(stdout);
}

/*
 * CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG only picks which channel carries the
 * console, it doesn't turn on blocking reads or install the interrupt-driven
 * driver, both need doing explicitly (mirrors ESP-IDF's own console/advanced
 * example). Without this, stdin stays non-blocking and fgets() returns
 * immediately with nothing, which is what was spinning the menu loop.
 */
static void init_console(void)
{
    fflush(stdout);
    fsync(fileno(stdout));

    // idf_monitor/minicom/screen send CR on Enter; move the caret properly on '\n' out.
    usb_serial_jtag_vfs_set_rx_line_endings(ESP_LINE_ENDINGS_CR);
    usb_serial_jtag_vfs_set_tx_line_endings(ESP_LINE_ENDINGS_CRLF);

    fcntl(fileno(stdout), F_SETFL, 0);
    fcntl(fileno(stdin), F_SETFL, 0);

    usb_serial_jtag_driver_config_t jtag_config = {
        .tx_buffer_size = 256,
        .rx_buffer_size = 256,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&jtag_config));
    usb_serial_jtag_vfs_use_driver();

    setvbuf(stdin, NULL, _IONBF, 0);
}

void app_main(void)
{
    init_console();
    print_chip_identity();
    print_reset_reason();

    char line[8];
    while (1) {
        print_menu();

        if (fgets(line, sizeof(line), stdin) == NULL) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (line[0] == '\n' || line[0] == '\r') {
            continue;
        }

        bool handled = false;
        for (size_t i = 0; i < sizeof(tests) / sizeof(tests[0]); i++) {
            if (tests[i].cmd == line[0]) {
                handled = true;
                esp_err_t result = tests[i].run();
                if (result == ESP_OK) {
                    printf("[PASS] %s\n", tests[i].name);
                } else if (result != ESP_ERR_NOT_SUPPORTED) {
                    printf("[FAIL] %s\n", tests[i].name);
                }
                break;
            }
        }
        if (!handled) {
            printf("Unknown command: %c\n", line[0]);
        }
    }
}
