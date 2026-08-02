cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS
    ${CMAKE_CURRENT_LIST_DIR}/../../tmc2209
    ${CMAKE_CURRENT_LIST_DIR}/../../rpc
    ${CMAKE_CURRENT_LIST_DIR}/../../shared/rpc_api)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(stef_firmware)
