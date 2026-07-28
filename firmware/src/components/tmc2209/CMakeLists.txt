# Deliberately no REQUIRES: this component depends on nothing, not even
# ESP-IDF. That is what lets firmware/test/unit compile the same sources
# natively. The control lines are here too, but only as levels behind
# tmc2209_lines_t, so no GPIO driver comes with them. Keep it that way.
idf_component_register(SRCS "tmc2209.c" "tmc2209_err.c" "tmc2209_frame.c" "tmc2209_lines.c" "tmc2209_reg.c"
                       INCLUDE_DIRS "include")
