# The composition root, and nothing else. Everything that used to live here
# offers a capability; this is the file that chooses which of them the image
# installs, and the only one nothing else calls.
#
# selftest_main.c is the older console self-test, kept but no longer built: its
# command menu reads stdin from the same port the RPC link now owns, and a port
# has one owner.
idf_component_register(SRCS "dev_main.c" "led_strip_encoder.c"
                        INCLUDE_DIRS "."
                        REQUIRES rpc rpc_bind tmc2209_bind
                        PRIV_REQUIRES esp_driver_rmt)
