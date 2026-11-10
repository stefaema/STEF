# Which drivers exist and on which pins, and the library's backends on real
# peripherals.
#
# REQUIRES tmc2209 rather than PRIV_REQUIRES because devices.h hands out
# tmc2209_t*, so anyone including it needs the library's headers too.
idf_component_register(SRCS "board.c" "backends.c" "ramp.c" "stepgen.c" "devices.c"
                       INCLUDE_DIRS "include"
                       PRIV_INCLUDE_DIRS "."
                       REQUIRES tmc2209
                       PRIV_REQUIRES esp_driver_uart esp_driver_gpio
                                     esp_driver_rmt esp_driver_pcnt)
