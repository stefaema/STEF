# REQUIRES, not PRIV_REQUIRES: fw_api.h names both components' types in its
# payloads, so whoever includes it needs their headers too.
idf_component_register(INCLUDE_DIRS "include"
                       REQUIRES rpc tmc2209)
