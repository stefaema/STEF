# Deliberately no REQUIRES: like tmc2209, this component depends on nothing,
# not even ESP-IDF. That is what lets firmware/test/unit compile the same
# sources natively, and what will let the PC's cffi build compile them a third
# time. Framing, the CRC and the field encoders live here; anything that knows
# about a UART, a task or a device belongs in main.
idf_component_register(SRCS "cobs.c" "crc16.c" "rpc_frame.c" "rpc_dispatch.c"
                       INCLUDE_DIRS "include")
