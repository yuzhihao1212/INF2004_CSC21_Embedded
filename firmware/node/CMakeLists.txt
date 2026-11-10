# MOSAIC sensing node: environmental sensors -> protocol v2 TELEMETRY over Wi-Fi.
# Per-node settings come from node_config.cmake (git-ignored, copy
# node_config.example.cmake) or -D options. Without them the node still
# builds and runs, but only reads its sensors.

# Explicit -D values win over the private defaults (important for unique IDs
# in separate build directories tomorrow). Never print the password.
foreach(setting MOSAIC_NODE_ID MOSAIC_PC_IP WIFI_SSID WIFI_PASSWORD)
    if (DEFINED ${setting})
        set(saved_${setting} "${${setting}}")
        set(saved_${setting}_defined TRUE)
    endif()
endforeach()
include(${CMAKE_CURRENT_LIST_DIR}/node_config.cmake OPTIONAL)
foreach(setting MOSAIC_NODE_ID MOSAIC_PC_IP WIFI_SSID WIFI_PASSWORD)
    if (saved_${setting}_defined)
        set(${setting} "${saved_${setting}}")
    endif()
endforeach()
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
option(MOSAIC_WIFI_DISABLE_POWER_SAVE "Disable Wi-Fi power saving for delivery experiments" OFF)
target_compile_definitions(mosaic_node PRIVATE
    MOSAIC_WIFI_DISABLE_POWER_SAVE=$<BOOL:${MOSAIC_WIFI_DISABLE_POWER_SAVE}>
)
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

if (MOSAIC_BUILD_RTOS)
    set(MOSAIC_RTOS_CORES 1 CACHE STRING "RTOS cores: 1 for sensors/network, 2 for audio integration")
    if (NOT MOSAIC_RTOS_CORES MATCHES "^[12]$")
        message(FATAL_ERROR "MOSAIC_RTOS_CORES must be 1 or 2")
    endif()
    set(MOSAIC_NODE_AUDIO_SOURCES "" CACHE STRING "Team audio task sources implementing mosaic_node_audio_task(void *)")
    set(MOSAIC_NODE_AUDIO_LIBRARIES "audio_capture;audio_dsp" CACHE STRING "Libraries for the team audio task")
    # Configure only the RTOS target; the existing node remains a fallback.
    add_library(freertos_config INTERFACE)
    target_include_directories(freertos_config INTERFACE ${CMAKE_CURRENT_LIST_DIR}/rtos)
    target_link_libraries(FreeRTOS-Kernel INTERFACE freertos_config)
    add_executable(mosaic_node_rtos node_main.c)
    set(MOSAIC_HEALTH_STALL_TASK 0 CACHE STRING "Fault injection: 0=off, 1=network, 2=environment")
    if (NOT MOSAIC_HEALTH_STALL_TASK MATCHES "^[012]$")
        message(FATAL_ERROR "MOSAIC_HEALTH_STALL_TASK must be 0, 1, or 2")
    endif()
    target_compile_definitions(mosaic_node_rtos PRIVATE MOSAIC_NODE_RTOS=1
        MOSAIC_RTOS_CORES=${MOSAIC_RTOS_CORES}
        MOSAIC_WIFI_DISABLE_POWER_SAVE=$<BOOL:${MOSAIC_WIFI_DISABLE_POWER_SAVE}>
        MOSAIC_HEALTH_STALL_TASK=${MOSAIC_HEALTH_STALL_TASK})
    target_include_directories(mosaic_node_rtos PRIVATE ${CMAKE_CURRENT_LIST_DIR} ${CMAKE_CURRENT_BINARY_DIR})
    target_link_libraries(mosaic_node_rtos mosaic_common mosaic_environment pico_stdlib
        pico_cyw43_arch_lwip_threadsafe_background hardware_watchdog FreeRTOS-Kernel-Heap4)
    target_compile_options(mosaic_node_rtos PRIVATE -Wall -Wextra)
    if (MOSAIC_NODE_AUDIO_SOURCES)
        if (NOT MOSAIC_RTOS_CORES STREQUAL "2")
            message(FATAL_ERROR "An audio task requires -DMOSAIC_RTOS_CORES=2")
        endif()
        target_sources(mosaic_node_rtos PRIVATE ${MOSAIC_NODE_AUDIO_SOURCES})
        target_compile_definitions(mosaic_node_rtos PRIVATE MOSAIC_NODE_AUDIO_ENABLED=1)
        target_link_libraries(mosaic_node_rtos ${MOSAIC_NODE_AUDIO_LIBRARIES})
    endif()
    pico_enable_stdio_usb(mosaic_node_rtos 1)
    pico_enable_stdio_uart(mosaic_node_rtos 0)
    pico_add_extra_outputs(mosaic_node_rtos)
endif()
