cmake_minimum_required(VERSION 3.16)

# tmc2209 and rpc are reusable libraries and rpc_api is the contract the PC
# compiles too, so all three live outside this project rather than under
# components/. What stays here is what binds them to this board.
set(EXTRA_COMPONENT_DIRS
    ${CMAKE_CURRENT_LIST_DIR}/../../tmc2209
    ${CMAKE_CURRENT_LIST_DIR}/../../rpc
    ${CMAKE_CURRENT_LIST_DIR}/../../shared)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(stef_firmware)
