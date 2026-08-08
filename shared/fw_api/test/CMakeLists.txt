# cmake -S shared/fw_api/test -B build && cmake --build build && ctest --test-dir build

cmake_minimum_required(VERSION 3.16)
project(fw_api_contract C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror)

set(FW_API_DIR ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(RPC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../portable/rpc)
set(TMC2209_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../portable/tmc2209)

add_executable(contract_check contract_check.c ${FW_API_DIR}/rpc_strerror.c)
target_include_directories(contract_check PRIVATE
    ${FW_API_DIR}/include
    ${RPC_DIR}/include
    ${TMC2209_DIR}/include)

enable_testing()
add_test(NAME fw_api_contract COMMAND contract_check)
