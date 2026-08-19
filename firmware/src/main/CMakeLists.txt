idf_component_register(SRCS "dev_main.c"
                        INCLUDE_DIRS "."
                        REQUIRES rpc rpc_bind tmc2209_bind)
