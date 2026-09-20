#include <stdio.h>
#include <inttypes.h>
#include "pico/stdlib.h"

#define PIR_PIN 16
#define READ_INTERVAL_MS 500

int main(void) {
    stdio_init_all();

    gpio_init(PIR_PIN);
    gpio_set_dir(PIR_PIN, GPIO_IN);

    // Give USB serial time to connect.
    sleep_ms(2000);

    printf("PIR test on GP%d\n", PIR_PIN);
    printf("Waiting 60 seconds for PIR sensor to stabilise...\n");

    sleep_ms(60000);

    printf("PIR stabilisation complete.\n");
    printf("Starting readings...\n\n");

    int previous_value = -1;

    while (true) {

        int raw_value = gpio_get(PIR_PIN) ? 1 : 0;

        uint64_t elapsed_ms = time_us_64() / 1000;

        printf("[%" PRIu64 " ms] PIR raw value: %d | %s\n",
               elapsed_ms,
               raw_value,
               raw_value ? "MOTION DETECTED" : "No motion");

        if (previous_value != -1 && raw_value != previous_value) {

            printf("[%" PRIu64 " ms] >>> Motion %s\n",
                   elapsed_ms,
                   raw_value ? "started" : "stopped");
        }

        previous_value = raw_value;

        sleep_ms(READ_INTERVAL_MS);
    }
}