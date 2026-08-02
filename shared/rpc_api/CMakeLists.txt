# The vocabulary both ends compile: namespaces, method numbers, payload layouts
# and status values. No sources, because a contract has none. It sits apart from
# the firmware because the PC implements the other half of it.
idf_component_register(INCLUDE_DIRS "include"
                       REQUIRES rpc)
