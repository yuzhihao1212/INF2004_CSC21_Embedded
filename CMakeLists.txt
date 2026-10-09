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

project(dht22_gp1 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
pico_sdk_init()

if (NOT TARGET tinyusb_device)
    message(FATAL_ERROR "USB stdio requires the SDK's TinyUSB submodule")
endif()

add_executable(dht22_gp1
    dht22_gp1.c
)

target_link_libraries(dht22_gp1
    pico_stdlib
)

pico_enable_stdio_usb(dht22_gp1 1)
pico_enable_stdio_uart(dht22_gp1 0)
pico_add_extra_outputs(dht22_gp1)

# Independent PIR test firmware, using the same SDK and USB stdio setup.
add_executable(pir_test
    pir_test.c
)

target_link_libraries(pir_test pico_stdlib)
pico_enable_stdio_usb(pir_test 1)
pico_enable_stdio_uart(pir_test 0)
pico_add_extra_outputs(pir_test)

# UART1 reads the CO2 sensor; printf() remains on USB only.
add_executable(acd1100_test acd1100_test.c)
target_link_libraries(acd1100_test pico_stdlib hardware_uart)
pico_enable_stdio_usb(acd1100_test 1)
pico_enable_stdio_uart(acd1100_test 0)
pico_add_extra_outputs(acd1100_test)

# Analog microphone on GP26 / ADC0, with summaries over USB serial.
add_executable(mic_test mic_test.c)
target_link_libraries(mic_test pico_stdlib hardware_adc)
pico_enable_stdio_usb(mic_test 1)
pico_enable_stdio_uart(mic_test 0)
pico_add_extra_outputs(mic_test)

# Combined MOSAIC sensor test; individual test targets remain available.
add_executable(mosaic_sensor_test
    mosaic_sensor_test.c
)
target_link_libraries(mosaic_sensor_test
    pico_stdlib
    hardware_adc
    hardware_uart
)
pico_enable_stdio_usb(mosaic_sensor_test 1)
pico_enable_stdio_uart(mosaic_sensor_test 0)
pico_add_extra_outputs(mosaic_sensor_test)

# Audio DSP / MFCC feature extraction (Moe).
add_executable(audio_dsp audio_dsp.c)
target_link_libraries(audio_dsp pico_stdlib hardware_adc)
pico_enable_stdio_usb(audio_dsp 1)
pico_enable_stdio_uart(audio_dsp 0)
pico_add_extra_outputs(audio_dsp)

add_executable(audio_dsp_capture audio_dsp_capture.c)
target_link_libraries(audio_dsp_capture pico_stdlib hardware_adc hardware_dma pico_multicore)
pico_enable_stdio_usb(audio_dsp_capture 1)
pico_enable_stdio_uart(audio_dsp_capture 0)
pico_add_extra_outputs(audio_dsp_capture)
