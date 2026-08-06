cmake_minimum_required(VERSION 3.16)
project(librpc C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror)

set(ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_library(rpc SHARED
    ${ROOT}/portable/rpc/cobs.c
    ${ROOT}/portable/rpc/crc16.c
    ${ROOT}/portable/rpc/rpc_frame.c
    ${ROOT}/shared/rpc_api/rpc_strerror.c
    ${ROOT}/portable/tmc2209/tmc2209_err.c
    ${ROOT}/portable/tmc2209/tmc2209_frame.c
    ${ROOT}/portable/tmc2209/tmc2209_reg.c)

target_include_directories(rpc PRIVATE
    ${ROOT}/portable/rpc/include
    ${ROOT}/shared/rpc_api/include
    ${ROOT}/portable/tmc2209/include)

set_target_properties(rpc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/build)
