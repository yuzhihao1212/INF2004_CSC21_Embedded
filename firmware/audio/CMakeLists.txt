
cmake_minimum_required(VERSION 3.13)

# Import Raspberry Pi Pico SDK
include("${PICO_SDK_PATH}/external/pico_sdk_import.cmake")

project(mosaic_audio C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

# ============================================================
# DSP module (Moe)
# ============================================================

add_library(audio_dsp STATIC
    audio_dsp.c
)

target_include_directories(audio_dsp PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(audio_dsp PUBLIC
    m
)

# ============================================================
# Microphone ADC + DMA capture module
# ============================================================

add_library(audio_capture STATIC
    audio_capture.c
)

target_include_directories(audio_capture PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(audio_capture PUBLIC
    pico_stdlib
    hardware_adc
    hardware_dma
)

# ============================================================
# DSP benchmark executable
# ============================================================

add_executable(audio_benchmark
    audio_benchmark.c
)

target_link_libraries(audio_benchmark PRIVATE
    pico_stdlib
    audio_capture
    audio_dsp
)

pico_enable_stdio_usb(audio_benchmark 1)
pico_enable_stdio_uart(audio_benchmark 0)

pico_add_extra_outputs(audio_benchmark)

# Own trained three-class model; retains the existing benchmark target.
add_executable(audio_talking
    audio_talking.c classifier_timing.c
    classifier/dsp_int8_candidate.c classifier/classifier_probabilities.c
    audio_signal_quality.c
)
target_link_libraries(audio_talking PRIVATE pico_stdlib audio_capture audio_dsp m)
target_compile_options(audio_talking PRIVATE -O2 -Wall -Wextra -Wno-array-parameter)
target_compile_definitions(audio_talking PRIVATE PICO_STDIO_USB_STDOUT_TIMEOUT_US=2000 PICO_STACK_SIZE=4096)
pico_enable_stdio_usb(audio_talking 1)
pico_enable_stdio_uart(audio_talking 0)
pico_add_extra_outputs(audio_talking)
