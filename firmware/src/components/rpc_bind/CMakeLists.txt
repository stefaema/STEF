# The method handlers, the trip and the USB link. The rpc component itself names
# no handler.
idf_component_register(SRCS "rpc_status.c" "rpc_sys.c" "rpc_raw.c" "rpc_relay.c" "rpc_link.c" "rpc_trip.c"
                       INCLUDE_DIRS "include"
                       PRIV_INCLUDE_DIRS "."
                       REQUIRES rpc fw_api
                       PRIV_REQUIRES tmc2209 tmc2209_bind esp_driver_usb_serial_jtag esp_timer esp_app_format spi_flash)
