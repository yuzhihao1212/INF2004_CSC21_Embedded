# Standalone sensor / DSP bring-up firmware. Each target builds its own .uf2.

add_executable(dht22_gp1
    dht22_gp1.c
)

target_link_libraries(dht22_gp1
    pico_stdlib
    mosaic_environment
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
    mosaic_environment
    pico_stdlib
    hardware_adc
    hardware_uart
)
pico_enable_stdio_usb(mosaic_sensor_test 1)
pico_enable_stdio_uart(mosaic_sensor_test 0)
pico_add_extra_outputs(mosaic_sensor_test)

# Explicit opt-in: not part of the default all target, and never flashed here.
set(MOSAIC_DHT22_VALIDATION_ATTEMPTS 100 CACHE STRING "DHT22 validation attempts (1..1000000)")
if (NOT MOSAIC_DHT22_VALIDATION_ATTEMPTS MATCHES "^[1-9][0-9]*$" OR
    MOSAIC_DHT22_VALIDATION_ATTEMPTS GREATER 1000000)
    message(FATAL_ERROR "MOSAIC_DHT22_VALIDATION_ATTEMPTS must be 1..1000000")
endif()
add_executable(dht22_pio_validation EXCLUDE_FROM_ALL dht22_pio_validation.c)
target_compile_definitions(dht22_pio_validation PRIVATE
    DHT22_VALIDATION_ATTEMPTS=${MOSAIC_DHT22_VALIDATION_ATTEMPTS})
target_compile_options(dht22_pio_validation PRIVATE -Wall -Wextra -Werror)
target_link_libraries(dht22_pio_validation mosaic_environment pico_stdlib)
pico_enable_stdio_usb(dht22_pio_validation 1)
pico_enable_stdio_uart(dht22_pio_validation 0)
pico_add_extra_outputs(dht22_pio_validation)
