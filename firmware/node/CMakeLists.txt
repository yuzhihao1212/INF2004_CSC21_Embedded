# MOSAIC sensing node: environmental sensors -> protocol v2 TELEMETRY over Wi-Fi.
# Per-node settings come from node_config.cmake (git-ignored, copy
# node_config.example.cmake) or -D options. Without them the node still
# builds and runs, but only reads its sensors.

include(${CMAKE_CURRENT_LIST_DIR}/node_config.cmake OPTIONAL)
foreach(setting MOSAIC_PC_IP WIFI_SSID WIFI_PASSWORD)
    if (NOT DEFINED ${setting})
        set(${setting} "")
    endif()
    # Escape for a C string literal.
    string(REPLACE "\\" "\\\\" ${setting}_C "${${setting}}")
    string(REPLACE "\"" "\\\"" ${setting}_C "${${setting}_C}")
endforeach()
if (NOT DEFINED MOSAIC_NODE_ID)
    set(MOSAIC_NODE_ID 1)
endif()
if (NOT MOSAIC_NODE_ID MATCHES "^[1-8]$")
    message(FATAL_ERROR "MOSAIC_NODE_ID must be 1..8, got '${MOSAIC_NODE_ID}'")
endif()
if (WIFI_SSID STREQUAL "" OR MOSAIC_PC_IP STREQUAL "")
    message(WARNING "mosaic_node: Wi-Fi or PC IP not set, so it will not send telemetry. "
                    "See firmware/node/node_config.example.cmake")
else()
    message(STATUS "mosaic_node: node ${MOSAIC_NODE_ID}, Wi-Fi '${WIFI_SSID}', PC ${MOSAIC_PC_IP}")
endif()
configure_file(node_config.h.in ${CMAKE_CURRENT_BINARY_DIR}/node_config.h @ONLY)

add_executable(mosaic_node node_main.c)
target_include_directories(mosaic_node PRIVATE ${CMAKE_CURRENT_LIST_DIR} ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(mosaic_node
    mosaic_common
    mosaic_environment
    pico_stdlib
    pico_cyw43_arch_lwip_threadsafe_background
)
target_compile_options(mosaic_node PRIVATE -Wall -Wextra)
pico_enable_stdio_usb(mosaic_node 1)
pico_enable_stdio_uart(mosaic_node 0)
pico_add_extra_outputs(mosaic_node)
