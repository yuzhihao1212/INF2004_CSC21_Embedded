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
#include "environment.h"
#include "dht22.h"
#include "sensors.h"

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
#define REPORT_INTERVAL_MS 2000

// Starting values in ADC counts: calibrate with your microphone's gain and
// classroom noise. These are debugging labels, NOT the MOSAIC ML classifier
// or calibrated sound-pressure levels. Below QUIET threshold means QUIET.
#define MIC_QUIET_THRESHOLD 80
#define MIC_LOUD_THRESHOLD 300
#if MIC_QUIET_THRESHOLD >= MIC_LOUD_THRESHOLD
#error "Microphone thresholds must be in increasing order"
#endif

typedef struct {
    environment_record_t env;
    uint16_t mic_min;
    uint16_t mic_max;
    uint16_t mic_peak_to_peak;
} sensor_data_t;

static uint64_t now_ms(void) {
    return time_us_64() / 1000;
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

static void print_report(const sensor_data_t *data) {
    const environment_record_t *r = &data->env;
    printf("\n==================================================\n");
    printf("MOSAIC SENSOR NODE\nTime: %" PRIu32 " ms\n\n", r->timestamp_ms);
    if ((r->validity_flags & ENV_DHT_VALID) == ENV_DHT_VALID) {
        char t[8], h[8];
        environment_format_x10(t, sizeof(t), r->temperature_x10);
        environment_format_x10(h, sizeof(h), (int16_t)r->humidity_x10);
        printf("Temperature : %s C\nHumidity    : %s %%\n", t, h);
    } else {
        printf("Temperature : INVALID\nHumidity    : INVALID\n");
    }
    printf("DHT22       : %s\n", environment_status_name(r->dht_status));
    printf("PIR         : %s\nPIR status  : %s\n",
           r->motion ? "MOTION" : "NO RECENT MOTION",
           environment_status_name(r->pir_status));
    if (r->validity_flags & ENV_CO2_VALID)
        printf("CO2         : %u ppm\n", (unsigned)r->co2_ppm);
    else
        printf("CO2         : %s\n", environment_status_name(r->co2_status));
    printf("CO2 status  : %s\nValidity    : 0x%02X\n",
           environment_status_name(r->co2_status), (unsigned)r->validity_flags);
    // Report the most recent 50 ms window, not a two-second average/maximum.
    printf("\nMicrophone (latest 50 ms window):\n");
    printf("  Min ADC   : %u\n  Max ADC   : %u\n  P-P       : %u\n  State     : %s\n",
           (unsigned int)data->mic_min, (unsigned int)data->mic_max,
           (unsigned int)data->mic_peak_to_peak, microphone_label(data->mic_peak_to_peak));
    printf("==================================================\n");
}

int main(void) {
    stdio_init_all();
    dht22_t dht;
    bool dht_ready = dht22_init(&dht, DHT_PIN);
    environment_pir_init(PIR_PIN);
    init_microphone();
    acd1100_t co2;
    acd1100_init(&co2, CO2_UART, CO2_TX_PIN, CO2_RX_PIN);
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
    if (!dht_ready)
        environment_apply_dht(&data.env, SENSOR_RESOURCE_ERROR, 0, 0, (uint32_t)now_ms());
    environment_pir_read(&data.env, PIR_PIN);
    uint64_t next_pir = 0, next_dht = 0, next_report = 0;
    while (true) {
        // Cooperative scheduling: tasks run when due, without long sleeps.
        // Scheduling from 'now' avoids bursts of catch-up reads after a delay.
        if (now_ms() >= next_pir) {
            environment_pir_read(&data.env, PIR_PIN);
            next_pir = now_ms() + PIR_INTERVAL_MS;
        }
        acd1100_service(&co2, &data.env);
        dht22_service(&dht, &data.env);
        if (dht_ready && !dht.active && now_ms() >= next_dht) {
            (void)dht22_start(&dht);
            next_dht = now_ms() + DHT_INTERVAL_MS;
        }
        read_microphone(&data);
        acd1100_service(&co2, &data.env);
        dht22_service(&dht, &data.env);
        environment_expire(&data.env, (uint32_t)now_ms());
        if (now_ms() >= next_report) {
            print_report(&data);
            next_report = now_ms() + REPORT_INTERVAL_MS;
        }
    }
}
