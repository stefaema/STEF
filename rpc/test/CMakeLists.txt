# Host-native unit tests for the framing library. No ESP-IDF, no toolchain, no
# hardware: the same sources the firmware runs and, later, the same ones the PC
# links through cffi.
#
#   cmake -S rpc/test -B build-unit && cmake --build build-unit
#   ctest --test-dir build-unit --output-on-failure
#
# Unity comes from ESP-IDF if IDF_PATH is set, so there is nothing to vendor
# and nothing to fetch. Point UNITY_DIR elsewhere if you have it standalone.

cmake_minimum_required(VERSION 3.16)
project(rpc_unit_tests C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror -g -O1)

set(RPC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/..)

if(NOT DEFINED UNITY_DIR)
    if(DEFINED ENV{IDF_PATH} AND EXISTS $ENV{IDF_PATH}/components/unity/unity/src/unity.c)
        set(UNITY_DIR $ENV{IDF_PATH}/components/unity/unity/src)
    endif()
endif()

if(NOT DEFINED UNITY_DIR OR NOT EXISTS ${UNITY_DIR}/unity.c)
    message(FATAL_ERROR
        "Unity not found. Enter a nix shell so IDF_PATH is set, "
        "or pass -DUNITY_DIR=/path/to/unity/src")
endif()

# Unity is third-party; do not hold it to our warning settings.
add_library(unity STATIC ${UNITY_DIR}/unity.c)
target_include_directories(unity PUBLIC ${UNITY_DIR})
target_compile_options(unity PRIVATE -w)

add_library(rpc STATIC
    ${RPC_DIR}/cobs.c
    ${RPC_DIR}/crc16.c
    ${RPC_DIR}/rpc_frame.c
    ${RPC_DIR}/rpc_dispatch.c)
target_include_directories(rpc PUBLIC ${RPC_DIR}/include)

add_executable(unit_tests
    main.c
    test_cobs.c
    test_rpc_frame.c)
target_link_libraries(unit_tests PRIVATE rpc unity)

enable_testing()
add_test(NAME rpc_unit COMMAND unit_tests)
