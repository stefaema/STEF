# What the rpc component alone cannot know: which methods exist and what they do. The
# component moves frames and names no handler; these are the handlers, plus the
# vocabulary both ends compile and the link that carries the bytes.
idf_component_register(SRCS "rpc_status.c" "rpc_sys.c" "rpc_raw.c" "rpc_relay.c" "rpc_link.c"
                       INCLUDE_DIRS "include"
                       PRIV_INCLUDE_DIRS "."
                       REQUIRES rpc fw_api
                       PRIV_REQUIRES tmc2209 tmc2209_bind esp_driver_usb_serial_jtag esp_timer esp_app_format spi_flash)
