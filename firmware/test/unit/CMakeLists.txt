# Host-native unit tests. No ESP-IDF, no toolchain, no hardware: this builds
# the same tmc2209 and rpc sources the firmware uses, against a mock port.
#
#   cmake -S firmware/test/unit -B build-unit && cmake --build build-unit
#   ctest --test-dir build-unit --output-on-failure
#
# Unity comes from ESP-IDF if IDF_PATH is set, so there is nothing to vendor
# and nothing to fetch. Point UNITY_DIR elsewhere if you have it standalone.

cmake_minimum_required(VERSION 3.16)
project(tmc2209_unit_tests C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror -g -O1)

set(TMC2209_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../src/components/tmc2209)
set(RPC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../src/components/rpc)
set(MAIN_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../src/main)

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
    ${TMC2209_DIR}/tmc2209_stepgen.c)
target_include_directories(tmc2209 PUBLIC ${TMC2209_DIR}/include)

# The framing and the wire format, built here for the same reason: they are the
# sources the firmware runs and, later, the ones the PC links through cffi.
add_library(rpc STATIC
    ${RPC_DIR}/cobs.c
    ${RPC_DIR}/crc16.c
    ${RPC_DIR}/rpc_wire.c
    ${RPC_DIR}/rpc_dispatch.c)
target_include_directories(rpc PUBLIC ${RPC_DIR}/include)

add_executable(unit_tests
    main.c
    mock_tmc2209.c
    test_frame.c
    test_reg.c
    test_device.c
    test_lines.c
    test_stepgen.c
    test_cobs.c
    test_wire.c
    test_rpc.c
    fake_devices.c
    fake_watchdog.c
    # The bridges. They live in main/ because they are where the two libraries
    # meet, and they include nothing from ESP-IDF, which is what lets them be
    # compiled here against the mock driver rather than against a cable.
    ${MAIN_DIR}/rpc_raw.c
    ${MAIN_DIR}/rpc_passthrough.c
    ${MAIN_DIR}/rpc_status.c)
target_include_directories(unit_tests PRIVATE ${MAIN_DIR})
target_link_libraries(unit_tests PRIVATE tmc2209 rpc unity)

enable_testing()
add_test(NAME firmware_unit COMMAND unit_tests)
