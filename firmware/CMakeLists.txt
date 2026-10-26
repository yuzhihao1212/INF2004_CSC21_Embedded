cmake_minimum_required(VERSION 3.13)

# Import the installed SDK before project(), as pico-examples does.
# Use its import file directly without a separate local import file.
if (NOT PICO_SDK_PATH)
    set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}")
endif()
if (NOT EXISTS "${PICO_SDK_PATH}/external/pico_sdk_import.cmake")
    message(FATAL_ERROR "Set PICO_SDK_PATH to your Raspberry Pi Pico SDK v1.5.1 directory")
endif()
set(PICO_BOARD pico_w CACHE STRING "Target board")
include("${PICO_SDK_PATH}/external/pico_sdk_import.cmake")

project(mosaic C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
pico_sdk_init()

if (NOT TARGET tinyusb_device)
    message(FATAL_ERROR "USB stdio requires the SDK's TinyUSB submodule")
endif()

# Shared headers (wire protocol, ...), linked as the mosaic_common library.
add_subdirectory(common)

# Standalone sensor / DSP bring-up firmware, one executable per test.
add_subdirectory(environment)
add_subdirectory(tests)
add_subdirectory(audio)

# The sensing node that sends telemetry to the PC gateway over Wi-Fi.
add_subdirectory(node)
