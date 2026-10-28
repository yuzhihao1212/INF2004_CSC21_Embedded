
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
    audio_signal_quality.c
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

# Optional richer training capture; existing benchmark remains a separate target.
add_executable(audio_sequence_capture audio_sequence_capture.c)
target_link_libraries(audio_sequence_capture PRIVATE pico_stdlib audio_capture audio_dsp)
pico_enable_stdio_usb(audio_sequence_capture 1)
pico_enable_stdio_uart(audio_sequence_capture 0)
pico_add_extra_outputs(audio_sequence_capture)

# Pretrained neural VAD plus a locally trained binary speech head.
# Local speech evidence plus an optional reference-comparison USB service.
add_executable(audio_talking
    audio_talking.c
    audio_stream.c
    reference_detector.c
    reference_service.c
    audio_raw_diagnostic.c
    pulsevad/pulsevad.c
    pulsevad/talking_detector.c
    audio_signal_quality.c
)
target_link_libraries(audio_talking PRIVATE pico_stdlib pico_multicore audio_capture m)
target_compile_options(audio_talking PRIVATE -O2 -Wall -Wextra -Wno-array-parameter)
target_compile_definitions(audio_talking PRIVATE PICO_STDIO_USB_STDOUT_TIMEOUT_US=2000 PICO_STACK_SIZE=4096)
pico_enable_stdio_usb(audio_talking 1)
pico_enable_stdio_uart(audio_talking 0)
pico_add_extra_outputs(audio_talking)

# ADC-only isolation build: capture and transmission occur in separate phases.
add_executable(audio_record_only audio_record_only.c audio_raw_diagnostic.c)
target_link_libraries(audio_record_only PRIVATE pico_stdlib hardware_adc hardware_dma)
target_compile_options(audio_record_only PRIVATE -O2 -Wall -Wextra)
target_compile_definitions(audio_record_only PRIVATE PICO_STDIO_USB_STDOUT_TIMEOUT_US=100000)
pico_enable_stdio_usb(audio_record_only 1)
pico_enable_stdio_uart(audio_record_only 0)
pico_add_extra_outputs(audio_record_only)
