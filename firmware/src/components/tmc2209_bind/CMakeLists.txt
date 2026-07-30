# What the tmc2209 library cannot know: which drivers exist, on which pins, and
# what to do with them when the PC goes quiet. The library takes backends; this
# is where they are met against real peripherals.
#
# REQUIRES tmc2209 rather than PRIV_REQUIRES because devices.h hands out
# tmc2209_t*, so anyone including it needs the library's headers too.
idf_component_register(SRCS "board.c" "backends.c" "devices.c" "watchdog.c"
                       INCLUDE_DIRS "include"
                       PRIV_INCLUDE_DIRS "."
                       REQUIRES tmc2209
                       PRIV_REQUIRES esp_driver_uart esp_driver_gpio esp_timer)
