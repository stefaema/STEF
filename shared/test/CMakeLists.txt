# cmake -S shared/test -B build && cmake --build build && ctest --test-dir build

cmake_minimum_required(VERSION 3.16)
project(rpc_api_contract C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Werror)

set(RPC_API_DIR ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(RPC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../rpc)

add_executable(contract_check contract_check.c)
target_include_directories(contract_check PRIVATE
    ${RPC_API_DIR}/rpc_api/include
    ${RPC_DIR}/include)

enable_testing()
add_test(NAME rpc_api_contract COMMAND contract_check)
