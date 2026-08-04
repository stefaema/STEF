cmake_minimum_required(VERSION 3.16)
project(librpc C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror)

set(ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_library(rpc SHARED
    ${ROOT}/rpc/cobs.c
    ${ROOT}/rpc/crc16.c
    ${ROOT}/rpc/rpc_frame.c
    ${ROOT}/shared/rpc_api/rpc_strerror.c
    ${ROOT}/tmc2209/tmc2209_err.c
    ${ROOT}/tmc2209/tmc2209_frame.c
    ${ROOT}/tmc2209/tmc2209_reg.c)

target_include_directories(rpc PRIVATE
    ${ROOT}/rpc/include
    ${ROOT}/shared/rpc_api/include
    ${ROOT}/tmc2209/include)

set_target_properties(rpc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
