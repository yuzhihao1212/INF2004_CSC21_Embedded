/*
 * MOSAIC integration test, based on this project's individual sensor tests.
 * DHT transition decoding adapted from pico-examples/gpio/dht_sensor/dht.c:
 * Copyright (c) 2020 Raspberry Pi (Trading) Ltd.
 * SPDX-License-Identifier: BSD-3-Clause
 */
#include <stdio.h>
#include <inttypes.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/uart.h"
#include "hardware/sync.h"

#define DHT_PIN 2
#define PIR_PIN 16
#define MIC_PIN 26
#define MIC_ADC_INPUT 0
#define CO2_UART uart1
#define CO2_TX_PIN 8
#define CO2_RX_PIN 9
#define PIR_INTERVAL_MS 100
#define MIC_WINDOW_MS 50
#define DHT_INTERVAL_MS 2500
#define CO2_INTERVAL_MS 2000
#define REPORT_INTERVAL_MS 2000
#define CO2_WARMUP_MS 120000
#define CO2_TIMEOUT_MS 1000

// Starting values in ADC counts: calibrate with your microphone's gain and
// classroom noise. These are debugging labels, NOT the MOSAIC ML classifier
// or calibrated sound-pressure levels. Below QUIET threshold means QUIET.
#define MIC_QUIET_THRESHOLD 80
#define MIC_LOUD_THRESHOLD 300
#if MIC_QUIET_THRESHOLD >= MIC_LOUD_THRESHOLD
#error "Microphone thresholds must be in increasing order"
#endif

typedef struct {
    float temperature;
    float humidity;
    bool dht_valid;
    bool motion;
    uint16_t co2_ppm;
    bool co2_valid;
    uint64_t co2_sample_ms;
    uint16_t mic_min;
    uint16_t mic_max;
    uint16_t mic_peak_to_peak;
} sensor_data_t;

// UART transaction state survives between main-loop iterations. No function
// waits for a complete reply, so a disconnected sensor cannot stall sampling.
typedef struct {
    bool waiting;
    uint8_t response[9];
    size_t received;
    uint64_t deadline_ms;
    uint64_t next_request_ms;
    const char *error;
} co2_state_t;

static uint64_t now_ms(void) {
    return time_us_64() / 1000;
}

static void init_dht22(void) {
    gpio_init(DHT_PIN);
    gpio_set_dir(DHT_PIN, GPIO_IN);
    gpio_pull_up(DHT_PIN);
}

// Latest DHT-only diagnostic is also included in the combined report.
static const char *dht_error = "not read yet";

// Every wait has a microsecond deadline. Unsigned subtraction also works
// across the 32-bit timer wrap. Called only with interrupts disabled.
static bool dht_wait_level(bool level, uint32_t timeout_us) {
    uint32_t start = time_us_32();
    while (gpio_get(DHT_PIN) != level) {
        if ((uint32_t)(time_us_32() - start) >= timeout_us) return false;
    }
    return true;
}

static bool read_dht22(sensor_data_t *data) {
    uint8_t bytes[5] = {0};
    uint bits = 0;
    const char *error = NULL;
    bool reading_bits = false;

    // DHT22/AM2302 start: LOW for at least 800 us (about 1 ms typical).
    // Preload LOW before enabling output; never actively drive the bus HIGH.
    gpio_put(DHT_PIN, 0);
    gpio_set_dir(DHT_PIN, GPIO_OUT);
    busy_wait_us_32(1100);

    uint32_t irq_state = save_and_disable_interrupts();
    gpio_pull_up(DHT_PIN);
    gpio_set_dir(DHT_PIN, GPIO_IN);

    // Synchronise to actual levels rather than assuming the first observed
    // transition's index. The bus first rises through its pull-up, then the
    // sensor responds with about 80 us LOW followed by about 80 us HIGH.
    if (!dht_wait_level(true, 40)) {
        error = "DATA did not rise after release (pull-up / stuck LOW)";
    } else if (!dht_wait_level(false, 250)) {
        error = "initial sensor response LOW timeout";
    } else if (!dht_wait_level(true, 120)) {
        error = "initial response HIGH timeout (response stayed LOW)";
    } else if (!dht_wait_level(false, 120)) {
        error = "initial response HIGH did not end / first bit LOW timeout";
    } else {
        reading_bits = true;
        for (bits = 0; bits < 40; ++bits) {
            // Each bit starts LOW (~50 us); measure only its HIGH pulse.
            if (!dht_wait_level(true, 100)) {
                error = "data-bit LOW did not end / HIGH timeout";
                break;
            }
            uint32_t high_start = time_us_32();
            if (!dht_wait_level(false, 120)) {
                error = "data-bit HIGH did not end / LOW timeout";
                break;
            }
            uint32_t high_us = time_us_32() - high_start;
            // Zero is ~26 us HIGH, one is ~70 us HIGH. 50 us separates them.
            bytes[bits / 8] = (uint8_t)((bytes[bits / 8] << 1) |
                                      (high_us > 50 ? 1 : 0));
        }
    }
    restore_interrupts(irq_state);
    // GPIO stays released with its pull-up enabled on both success and error.
    // All diagnostics occur AFTER capture and interrupt restoration.
    if (error) {
        dht_error = error;
        printf("DHT22 ERROR: %s\n", error);
        if (reading_bits) {
            printf("DHT22: failed at data bit %u (1-based)\n", bits + 1);
        }
        printf("DHT22: fewer than 40 bits received (%u/40)\n", bits);
        return false;
    }

    printf("DHT raw: %02X %02X %02X %02X %02X\n",
           (unsigned int)bytes[0], (unsigned int)bytes[1],
           (unsigned int)bytes[2], (unsigned int)bytes[3], (unsigned int)bytes[4]);
    uint8_t checksum = (uint8_t)(bytes[0] + bytes[1] + bytes[2] + bytes[3]);
    if (checksum != bytes[4]) {
        dht_error = "checksum validation failed";
        printf("DHT22 ERROR: checksum calculated=%02X received=%02X\n",
               (unsigned int)checksum, (unsigned int)bytes[4]);
        return false;
    }
    data->humidity = ((bytes[0] << 8) | bytes[1]) / 10.0f;
    data->temperature = (((bytes[2] & 0x7f) << 8) | bytes[3]) / 10.0f;
    // DHT22 temperature uses sign/magnitude, not two's complement.
    if (bytes[2] & 0x80) data->temperature = -data->temperature;
    dht_error = NULL;
    return true;
}

static void init_pir(void) {
    gpio_init(PIR_PIN);
    gpio_set_dir(PIR_PIN, GPIO_IN);
    gpio_pull_down(PIR_PIN); // Disconnected OUT reads LOW, not proof of absence.
}

static bool read_pir(void) {
    return gpio_get(PIR_PIN);
}

static void poll_pir(sensor_data_t *data) {
    bool motion = read_pir();
    if (motion != data->motion) {
        printf("[%" PRIu64 " ms] >>> PIR: Motion %s\n",
               now_ms(), motion ? "started" : "stopped");
    }
    data->motion = motion;
}

static void init_microphone(void) {
    adc_init();
    adc_gpio_init(MIC_PIN);
    adc_select_input(MIC_ADC_INPUT);
}

static void read_microphone(sensor_data_t *data) {
    uint16_t minimum = 4095;
    uint16_t maximum = 0;
    uint64_t end_us = time_us_64() + MIC_WINDOW_MS * 1000;
    // A short, bounded sampling window. No printing inside this loop.
    // Other tasks run between windows: this is not continuous audio recording
    // or a fixed-rate acquisition system. ADC/USB noise contributes to P-P.
    do {
        uint16_t sample = adc_read();
        if (sample < minimum) minimum = sample;
        if (sample > maximum) maximum = sample;
    } while (time_us_64() < end_us);
    data->mic_min = minimum;
    data->mic_max = maximum;
    data->mic_peak_to_peak = maximum - minimum;
}

static const char *microphone_label(uint16_t amplitude) {
    if (amplitude >= MIC_LOUD_THRESHOLD) return "LOUD";
    if (amplitude >= MIC_QUIET_THRESHOLD) return "SOUND";
    return "QUIET";
}

static void init_acd1100(void) {
    uart_init(CO2_UART, 1200);
    gpio_set_function(CO2_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(CO2_RX_PIN, GPIO_FUNC_UART);
    uart_set_hw_flow(CO2_UART, false, false);
    uart_set_format(CO2_UART, 8, 1, UART_PARITY_NONE);
    // A nine-byte reply fits in the RX FIFO while a 50 ms mic window runs.
    uart_set_fifo_enabled(CO2_UART, true);
}

static const char *validate_co2(const uint8_t *r) {
    if (r[0] != 0xFE || r[1] != 0xA6) return "Invalid frame header";
    if (r[2] != 0x04) return "Invalid frame length";
    if (r[3] != 0x01) return "Invalid response command";
    uint8_t checksum = 0;
    // Include both reserved bytes; exclude the FE prefix and checksum byte.
    for (size_t i = 1; i < 8; ++i) checksum = (uint8_t)(checksum + r[i]);
    if (checksum != r[8]) return "Invalid checksum";
    return NULL;
}

static void co2_failure(sensor_data_t *data, co2_state_t *state,
                        const char *reason) {
    data->co2_valid = false; // Never display an old reading as current on failure.
    state->waiting = false;
    state->error = reason;
    printf("[%" PRIu64 " ms] CO2 ERROR: %s\n", now_ms(), reason);
    if (state->received) {
        printf("RX:");
        for (size_t i = 0; i < state->received; ++i) {
            printf(" %02X", (unsigned int)state->response[i]);
        }
        printf("\n");
    }
}

static void service_acd1100(sensor_data_t *data, co2_state_t *state,
                           uint64_t warmup_end_ms) {
    uint64_t now = now_ms();
    if (now < warmup_end_ms) return;

    if (state->waiting) {
        // At most nine bytes per call; getc is only used when data is available.
        while (state->received < sizeof(state->response) && uart_is_readable(CO2_UART)) {
            state->response[state->received++] = (uint8_t)uart_getc(CO2_UART);
        }
        if (state->received == sizeof(state->response)) {
            const char *error = validate_co2(state->response);
            if (error) {
                co2_failure(data, state, error);
            } else {
                data->co2_ppm = (state->response[4] << 8) | state->response[5];
                data->co2_valid = true;
                data->co2_sample_ms = now;
                state->error = NULL;
                state->waiting = false;
            }
        } else if (now >= state->deadline_ms) {
            co2_failure(data, state, "UART timeout (incomplete 9-byte response)");
        }
        return;
    }

    if (now < state->next_request_ms) return;
    state->next_request_ms = now + CO2_INTERVAL_MS;
    state->received = 0;
    // Drain stale data with a fixed bound, even if the input is noisy.
    for (uint i = 0; i < 32 && uart_is_readable(CO2_UART); ++i) {
        (void)uart_getc(CO2_UART);
    }
    if (uart_is_readable(CO2_UART)) {
        co2_failure(data, state, "UART receive buffer did not clear");
        return;
    }
    // Only read CO2. No configuration, calibration, or reset commands.
    // Five bytes fit in the empty TX FIFO; flow control is disabled.
    static const uint8_t request[] = {0xFE, 0xA6, 0x00, 0x01, 0xA7};
    uart_write_blocking(CO2_UART, request, sizeof(request));
    state->deadline_ms = now_ms() + CO2_TIMEOUT_MS;
    state->waiting = true;
}

static void print_report(const sensor_data_t *data, const co2_state_t *co2,
                         uint64_t warmup_end_ms) {
    uint64_t now = now_ms();
    printf("\n==================================================\n");
    printf("MOSAIC SENSOR NODE\nTime: %" PRIu64 " ms\n\n", now);
    if (data->dht_valid) {
        printf("Temperature : %.1f C\nHumidity    : %.1f %%\n",
               data->temperature, data->humidity);
    } else {
        printf("Temperature : ERROR\nHumidity    : ERROR\n");
        printf("DHT22       : %s\n", dht_error ? dht_error : "read failed");
    }
    printf("\nPIR         : %s (raw %u)\n\n",
           data->motion ? "MOTION DETECTED" : "No motion detected",
           (unsigned int)data->motion);
    if (now < warmup_end_ms) {
        printf("CO2         : WARMING UP (%" PRIu64 " seconds remaining)\n",
               (warmup_end_ms - now + 999) / 1000);
    } else if (data->co2_valid) {
        printf("CO2         : %u ppm (sample age: %" PRIu64 " ms)\n",
               (unsigned int)data->co2_ppm, now - data->co2_sample_ms);
    } else if (co2->error) {
        printf("CO2         : ERROR - %s\n", co2->error);
    } else {
        printf("CO2         : waiting for first response\n");
    }
    // Report the most recent 50 ms window, not a two-second average/maximum.
    printf("\nMicrophone (latest 50 ms window):\n");
    printf("  Min ADC   : %u\n  Max ADC   : %u\n  P-P       : %u\n  State     : %s\n",
           (unsigned int)data->mic_min, (unsigned int)data->mic_max,
           (unsigned int)data->mic_peak_to_peak, microphone_label(data->mic_peak_to_peak));
    printf("==================================================\n");
}

int main(void) {
    stdio_init_all();
    init_dht22();
    init_pir();
    init_microphone();
    init_acd1100();
    // Assume sensor power is already on. A Pico reset restarts this timer;
    // independently power-cycling the sensor requires restarting the test.
    uint64_t warmup_end_ms = now_ms() + CO2_WARMUP_MS;
    sleep_ms(2000); // USB enumeration and initial DHT22 power-up only.

    printf("MOSAIC Sensor Integration Test\n\n");
    printf("DHT22 DATA : GP2\nPIR OUT    : GP16\n");
    printf("CO2 TX     : GP9 / UART1 RX\nCO2 RX     : GP8 / UART1 TX\n");
    printf("MIC AUD    : GP26 / ADC0\n\n");
    printf("CO2: 120-second warm-up; other sensors start now. UART1: 1200 8N1.\n");
    printf("PIR may be unstable for 30-60 seconds; LOW means no motion detected.\n");
    printf("Microphone thresholds need calibration; labels are not an ML classifier.\n");
    printf("Timestamps are milliseconds since Pico boot.\n");

    sensor_data_t data = {0};
    co2_state_t co2 = {.next_request_ms = warmup_end_ms};
    data.motion = read_pir(); // Establish baseline without inventing an edge.
    uint64_t next_pir = 0, next_dht = 0, next_report = 0;
    while (true) {
        // Cooperative scheduling: tasks run when due, without long sleeps.
        // Scheduling from 'now' avoids bursts of catch-up reads after a delay.
        if (now_ms() >= next_pir) {
            poll_pir(&data);
            next_pir = now_ms() + PIR_INTERVAL_MS;
        }
        service_acd1100(&data, &co2, warmup_end_ms);
        if (now_ms() >= next_dht) {
            data.dht_valid = read_dht22(&data);
            next_dht = now_ms() + DHT_INTERVAL_MS;
        }
        read_microphone(&data);
        service_acd1100(&data, &co2, warmup_end_ms);
        if (now_ms() >= next_report) {
            print_report(&data, &co2, warmup_end_ms);
            next_report = now_ms() + REPORT_INTERVAL_MS;
        }
    }
}
