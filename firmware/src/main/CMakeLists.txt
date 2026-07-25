idf_component_register(SRCS "selftest_main.c" "led_strip_encoder.c"
                        INCLUDE_DIRS "."
                        PRIV_REQUIRES esp_driver_rmt spi_flash esp_driver_usb_serial_jtag)
