/**
 * Adapted from pico-examples/gpio/dht_sensor/dht.c.
 * Copyright (c) 2020 Raspberry Pi (Trading) Ltd.
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"

#define DHT_PIN 1
#define MAX_TIMINGS 85
#define PULSE_TIMEOUT_US 255

typedef struct {
    float humidity;
    float temp_celsius;
} dht_reading;

static bool read_from_dht(dht_reading *result) {
    uint8_t data[5] = {0};
    uint last = 1;
    uint bits = 0;

    // Start signal: hold DATA low, then release it to the pull-up.
    gpio_put(DHT_PIN, 0);
    gpio_set_dir(DHT_PIN, GPIO_OUT);
    sleep_ms(20);

    // USB interrupts must not stretch the measured pulses. Restore them
    // on every exit; only the short, bounded pulse capture is protected.
    uint32_t irq_state = save_and_disable_interrupts();
    gpio_set_dir(DHT_PIN, GPIO_IN);
    bool timed_out = false;

    // Follow the official example's transitions: initial release, sensor
    // response (about 80 us low / 80 us high), then 40 MSB-first bits.
    for (uint i = 0; i < MAX_TIMINGS && bits < 40; ++i) {
        uint32_t start = time_us_32();
        while (gpio_get(DHT_PIN) == last) {
            if ((uint32_t)(time_us_32() - start) >= PULSE_TIMEOUT_US) {
                timed_out = true;
                break;
            }
            busy_wait_us_32(1);
        }
        uint32_t duration = time_us_32() - start;
        if (timed_out) {
            break;
        }
        last = gpio_get(DHT_PIN);

        // Each bit starts with ~50 us low. Its HIGH pulse is ~26-28 us
        // for zero or ~70 us for one. Use actual time, not loop counts.
        if (i >= 4 && (i % 2) == 0) {
            data[bits / 8] <<= 1;
            if (duration > 40) {
                data[bits / 8] |= 1;
            }
            ++bits;
        }
    }
    restore_interrupts(irq_state);

    if (timed_out || bits != 40 ||
        data[4] != ((data[0] + data[1] + data[2] + data[3]) & 0xff)) {
        return false;
    }

    // DHT22 values are tenths; temperature is sign/magnitude, not two's complement.
    result->humidity = (float)((data[0] << 8) | data[1]) / 10.0f;
    result->temp_celsius = (float)(((data[2] & 0x7f) << 8) | data[3]) / 10.0f;
    if (data[2] & 0x80) {
        result->temp_celsius = -result->temp_celsius;
    }
    return true;
}

int main(void) {
    stdio_init_all();
    gpio_init(DHT_PIN);
    gpio_set_dir(DHT_PIN, GPIO_IN);
    gpio_pull_up(DHT_PIN);
    sleep_ms(2000); // Allow USB enumeration and sensor power-up.

    while (true) {
        dht_reading reading;
        if (read_from_dht(&reading)) {
            printf("DHT22 Reading\n");
            printf("Temperature: %.1f C\n", reading.temp_celsius);
            printf("Humidity: %.1f %%\n", reading.humidity);
            printf("-------------------------\n");
        } else {
            printf("DHT22 read failed - timeout or checksum error\n");
        }
        sleep_ms(2500);
    }
}
