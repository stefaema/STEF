# cmake -S tmc2209/test -B build && cmake --build build && ctest --test-dir build

cmake_minimum_required(VERSION 3.16)
project(tmc2209_unit_tests C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror -g -O1)

set(TMC2209_DIR ${CMAKE_CURRENT_SOURCE_DIR}/..)

if(NOT DEFINED UNITY_DIR)
    if(DEFINED ENV{UNITY_DIR})
        set(UNITY_DIR $ENV{UNITY_DIR})
    elseif(DEFINED ENV{IDF_PATH} AND EXISTS $ENV{IDF_PATH}/components/unity/unity/src/unity.c)
        set(UNITY_DIR $ENV{IDF_PATH}/components/unity/unity/src)
    endif()
endif()

if(NOT DEFINED UNITY_DIR OR NOT EXISTS ${UNITY_DIR}/unity.c)
    message(FATAL_ERROR
        "Unity not found. Enter this module's nix shell, which sets UNITY_DIR, "
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

target_include_directories(tmc2209 PRIVATE ${TMC2209_DIR})

add_executable(unit_tests
    main.c
    mock_tmc2209.c
    test_frame.c
    test_reg.c
    test_device.c
    test_lines.c
    test_stepgen.c)
target_link_libraries(unit_tests PRIVATE tmc2209 unity)

enable_testing()
add_test(NAME tmc2209_unit COMMAND unit_tests)
