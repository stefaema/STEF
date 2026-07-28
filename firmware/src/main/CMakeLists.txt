# dev_main is the bench image. selftest_main.c is the older console self-test,
# kept but no longer built: its command menu reads stdin from the same port the
# RPC link now owns, and a port has one owner.
idf_component_register(SRCS "dev_main.c" "rpc_link.c" "rpc_status.c" "rpc_sys.c" "rpc_raw.c" "rpc_passthrough.c" "board.c" "backends.c" "devices.c" "watchdog.c" "led_strip_encoder.c"
                        INCLUDE_DIRS "."
                        REQUIRES rpc tmc2209
                        PRIV_REQUIRES esp_driver_rmt spi_flash esp_driver_usb_serial_jtag esp_driver_uart esp_driver_gpio esp_timer esp_app_format)
