# Deliberately no REQUIRES: this component depends on nothing, not even
# ESP-IDF. That is what lets firmware/test/unit compile the same sources
# natively. Keep it that way; GPIO belongs to the actuator layer above.
idf_component_register(SRCS "tmc2209.c" "tmc2209_err.c" "tmc2209_frame.c" "tmc2209_reg.c"
                       INCLUDE_DIRS "include")
