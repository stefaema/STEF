# The bind layer only. tmc2209/test and rpc/test cover the libraries.
# cmake -S firmware/test/unit -B build && cmake --build build && ctest --test-dir build

cmake_minimum_required(VERSION 3.16)
project(firmware_unit_tests C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror -g -O1)

set(ROOT_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../..)
set(TMC2209_DIR ${ROOT_DIR}/tmc2209)
set(RPC_DIR ${ROOT_DIR}/rpc)
set(RPC_API_DIR ${ROOT_DIR}/shared/rpc_api)
set(RPC_BIND_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../src/components/rpc_bind)
set(TMC_BIND_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../src/components/tmc2209_bind)

if(NOT DEFINED UNITY_DIR)
    if(DEFINED ENV{IDF_PATH} AND EXISTS $ENV{IDF_PATH}/components/unity/unity/src/unity.c)
        set(UNITY_DIR $ENV{IDF_PATH}/components/unity/unity/src)
    endif()
endif()

if(NOT DEFINED UNITY_DIR OR NOT EXISTS ${UNITY_DIR}/unity.c)
    message(FATAL_ERROR
        "Unity not found. Enter the firmware nix shell so IDF_PATH is set, "
        "or pass -DUNITY_DIR=/path/to/unity/src")
endif()

# Unity is third-party; do not hold it to our warning settings.
add_library(unity STATIC ${UNITY_DIR}/unity.c)
target_include_directories(unity PUBLIC ${UNITY_DIR})
target_compile_options(unity PRIVATE -w)

add_library(tmc2209 STATIC
    ${TMC2209_DIR}/tmc2209.c
    ${TMC2209_DIR}/tmc2209_err.c
    ${TMC2209_DIR}/tmc2209_frame.c
    ${TMC2209_DIR}/tmc2209_lines.c
    ${TMC2209_DIR}/tmc2209_reg.c
    ${TMC2209_DIR}/tmc2209_stepgen.c
    ${TMC2209_DIR}/tmc2209_uart.c)
target_include_directories(tmc2209 PUBLIC ${TMC2209_DIR}/include)

add_library(rpc STATIC
    ${RPC_DIR}/cobs.c
    ${RPC_DIR}/crc16.c
    ${RPC_DIR}/rpc_frame.c
    ${RPC_DIR}/rpc_dispatch.c)
target_include_directories(rpc PUBLIC ${RPC_DIR}/include)

add_executable(unit_tests
    main.c
    test_rpc.c
    fake_devices.c
    ${TMC2209_DIR}/test/mock_tmc2209.c

    ${RPC_BIND_DIR}/rpc_raw.c
    ${RPC_BIND_DIR}/rpc_relay.c
    ${RPC_BIND_DIR}/rpc_status.c)

# rpc_status.h is private to rpc_bind, so both of its directories are named.
# devices.h comes from tmc2209_bind; the tests link a fake for it.
target_include_directories(unit_tests PRIVATE
    ${RPC_BIND_DIR} ${RPC_BIND_DIR}/include ${TMC_BIND_DIR}/include
    ${RPC_API_DIR}/include ${TMC2209_DIR}/test)
target_link_libraries(unit_tests PRIVATE tmc2209 rpc unity)

enable_testing()
add_test(NAME firmware_unit COMMAND unit_tests)
