#include <stdio.h>
#include <inttypes.h>
#include "pico/stdlib.h"
#include "hardware/uart.h"

#define SENSOR_UART uart1
#define UART_TX_PIN 8
#define UART_RX_PIN 9
#define UART_BAUD_RATE 1200
#define WARMUP_SECONDS 120
#define RESPONSE_TIMEOUT_MS 1000
#define MEASUREMENT_INTERVAL_MS 2000

static uint64_t elapsed_ms(void) {
    return time_us_64() / 1000;
}

// Dump even partial replies so wiring/protocol problems can be investigated.
static void print_rx(const uint8_t *bytes, size_t count) {
    printf("RX:");
    for (size_t i = 0; i < count; ++i) {
        printf(" %02X", (unsigned int)bytes[i]);
    }
    printf("\n");
}

static void read_co2(void) {
    // This is the only command transmitted: read CO2, never configure/calibrate.
    static const uint8_t request[] = {0xFE, 0xA6, 0x00, 0x01, 0xA7};
    uint8_t response[9];
    size_t received = 0;

    // Discard any late reply or stale bytes before starting a fresh request.
    // Bound this operation too, in case unexpected data arrives continuously.
    absolute_time_t drain_deadline = make_timeout_time_ms(100);
    while (uart_is_readable(SENSOR_UART)) {
        if (time_reached(drain_deadline)) {
            printf("[%" PRIu64 " ms] ERROR: UART receive buffer did not clear\n",
                   elapsed_ms());
            return;
        }
        (void)uart_getc(SENSOR_UART);
    }

    uart_write_blocking(SENSOR_UART, request, sizeof(request));

    // At 1200 baud, 8N1 uses 10 bits per byte: a nine-byte reply takes
    // about 75 ms on the wire. One second allows sensor processing time.
    // Check readability before each getc so a missing sensor cannot hang us.
    absolute_time_t deadline = make_timeout_time_ms(RESPONSE_TIMEOUT_MS);
    while (received < sizeof(response) && !time_reached(deadline)) {
        if (uart_is_readable(SENSOR_UART)) {
            response[received++] = (uint8_t)uart_getc(SENSOR_UART);
        } else {
            sleep_ms(1);
        }
    }

    if (received != sizeof(response)) {
        printf("[%" PRIu64 " ms] ERROR: UART response timeout (%u/9 bytes)\n",
               elapsed_ms(), (unsigned int)received);
        if (received > 0) {
            print_rx(response, received);
        }
        return;
    }

    // Expected frame: FE A6 04 01 D1 D2 D3 D4 CS.
    // Length 04 means four data bytes, including the two reserved bytes.
    if (response[0] != 0xFE || response[1] != 0xA6 ||
        response[2] != 0x04 || response[3] != 0x01) {
        printf("[%" PRIu64 " ms] ERROR: Invalid frame header\n", elapsed_ms());
        print_rx(response, received);
        return;
    }

    // Sum A6 through D4, excluding FE and CS; keep only the low eight bits.
    uint8_t checksum = 0;
    for (size_t i = 1; i < 8; ++i) {
        checksum = (uint8_t)(checksum + response[i]);
    }
    if (checksum != response[8]) {
        printf("[%" PRIu64 " ms] ERROR: Invalid checksum (expected %02X)\n",
               elapsed_ms(), (unsigned int)checksum);
        print_rx(response, received);
        return;
    }

    // D1 is the high byte and D2 is the low byte. D3/D4 are reserved,
    // but still participate in the checksum above.
    uint16_t co2_ppm = (response[4] << 8) | response[5];
    printf("[%" PRIu64 " ms] CO2: %u ppm\n", elapsed_ms(), (unsigned int)co2_ppm);
}

int main(void) {
    // printf() uses USB; UART stdio is disabled in CMake.
    stdio_init_all();

    // UART1 is dedicated to the sensor: GP8 TX -> sensor RX,
    // sensor TX -> level shifter/divider -> GP9 RX.
    uart_init(SENSOR_UART, UART_BAUD_RATE);
    gpio_set_function(UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_PIN, GPIO_FUNC_UART);
    uart_set_hw_flow(SENSOR_UART, false, false);
    uart_set_format(SENSOR_UART, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(SENSOR_UART, true);

    sleep_ms(2000); // Allow USB serial to initialise.
    printf("ACD1100 CO2 test started\n");
    printf("UART1: 1200 baud, 8N1, no flow control; TX=GP8, RX=GP9\n");
    printf("WARNING: ACD1100 requires approximately 120 seconds of warm-up after power-on.\n");
    printf("Waiting a full 120 seconds before sending read commands.\n");
    printf("Timestamps are milliseconds since Pico boot.\n");

    // Actually wait, with progress so the board does not appear frozen.
    // This wait repeats after every Pico reset, even if the sensor stayed powered.
    for (unsigned int seconds = 0; seconds < WARMUP_SECONDS; seconds += 10) {
        printf("[%" PRIu64 " ms] Warming up: %u/%u seconds\n",
               elapsed_ms(), seconds, (unsigned int)WARMUP_SECONDS);
        sleep_ms(10000);
    }
    printf("[%" PRIu64 " ms] Warm-up complete: 120/120 seconds. Starting measurements.\n",
           elapsed_ms());

    while (true) {
        // Include the transaction time in the two-second request interval.
        absolute_time_t next_read = make_timeout_time_ms(MEASUREMENT_INTERVAL_MS);
        read_co2();
        sleep_until(next_read);
    }
}
