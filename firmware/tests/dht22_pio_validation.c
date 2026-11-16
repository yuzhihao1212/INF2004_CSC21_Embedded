/* Hardware evidence collector. Uses the production driver without IRQ changes.
 * USB output and pulse inspection occur only after service has stopped PIO/DMA.
 * Observed duration includes polling, cleanup and decode; it is not wire time.
 */
#include "dht22.h"
#include "hardware/clocks.h"
#include "pico/stdlib.h"
#include <inttypes.h>
#include <stdio.h>

#ifndef DHT22_VALIDATION_ATTEMPTS
#define DHT22_VALIDATION_ATTEMPTS 100
#endif
_Static_assert(DHT22_VALIDATION_ATTEMPTS >= 1 && DHT22_VALIDATION_ATTEMPTS <= 1000000,
               "Keep attempt and pulse counters within uint32_t");

#define DHT_PIN 2u
#define ATTEMPT_INTERVAL_US UINT64_C(2500000)
#define SERVICE_SLEEP_US 100u

typedef struct {
    uint32_t count;
    uint64_t minimum, maximum, total;
} duration_stats_t;

typedef struct {
    uint32_t count, minimum, maximum;
} pulse_range_t;

typedef struct {
    pulse_range_t response_low, response_high, bit_low, bit_high;
    pulse_range_t zero_high, one_high;
} pulse_stats_t;

typedef struct {
    uint32_t attempts, started, valid, complete_buffers, start_errors, init_errors;
    uint32_t ok, timeout, checksum, protocol, other;
    duration_stats_t all, complete, valid_duration, timed_out;
    pulse_stats_t pulses;
} validation_stats_t;

static void add_duration(duration_stats_t *s, uint64_t us) {
    if (!s->count || us < s->minimum) s->minimum = us;
    if (!s->count || us > s->maximum) s->maximum = us;
    s->total += us;
    ++s->count;
}

static void add_pulse(pulse_range_t *s, uint32_t us) {
    if (!s->count || us < s->minimum) s->minimum = us;
    if (!s->count || us > s->maximum) s->maximum = us;
    ++s->count;
}

static void add_pulses(pulse_stats_t *s, const uint32_t p[82], bool valid) {
    add_pulse(&s->response_low, p[0]);
    add_pulse(&s->response_high, p[1]);
    for (unsigned i = 0; i < 40; ++i) {
        uint32_t high = p[3 + 2 * i];
        add_pulse(&s->bit_low, p[2 + 2 * i]);
        add_pulse(&s->bit_high, high);
        /* Classify bits only for valid frames; malformed HIGHs stay raw. */
        if (valid) add_pulse(high >= 50 ? &s->one_high : &s->zero_high, high);
    }
}

static void print_duration(const char *name, const duration_stats_t *s) {
    if (!s->count) {
        printf("duration scope=%s n=0 us=NA\n", name);
        return;
    }
    printf("duration scope=%s n=%" PRIu32 " min_us=%" PRIu64
           " max_us=%" PRIu64 " avg_us=%" PRIu64 "\n",
           name, s->count, s->minimum, s->maximum, s->total / s->count);
}

static void print_range(const char *name, const pulse_range_t *s) {
    if (!s->count) {
        printf("pulse scope=%s n=0 us=NA\n", name);
        return;
    }
    printf("pulse scope=%s n=%" PRIu32 " min_us=%" PRIu32 " max_us=%" PRIu32 "\n",
           name, s->count, s->minimum, s->maximum);
}

static void print_summary(const validation_stats_t *s) {
    printf("\nSUMMARY requested=%u attempts=%" PRIu32 " started=%" PRIu32
           " valid=%" PRIu32 " complete_buffers=%" PRIu32 "\n",
           (unsigned)DHT22_VALIDATION_ATTEMPTS, s->attempts, s->started,
           s->valid, s->complete_buffers);
    printf("status ok=%" PRIu32 " timeout=%" PRIu32 " checksum=%" PRIu32
           " protocol=%" PRIu32 " other=%" PRIu32
           " start_errors=%" PRIu32 " init_errors=%" PRIu32 "\n",
           s->ok, s->timeout, s->checksum, s->protocol, s->other,
           s->start_errors, s->init_errors);
    if (s->attempts)
        printf("valid_rate_x100_percent=%" PRIu64 "\n",
               (uint64_t)s->valid * 10000 / s->attempts);
    print_duration("all_started", &s->all);
    print_duration("complete_buffers", &s->complete);
    print_duration("valid", &s->valid_duration);
    print_duration("timeouts", &s->timed_out);
    /* The first four ranges include complete malformed/checksum/range frames. */
    print_range("complete_response_low", &s->pulses.response_low);
    print_range("complete_response_high", &s->pulses.response_high);
    print_range("complete_bit_low", &s->pulses.bit_low);
    print_range("complete_bit_high", &s->pulses.bit_high);
    print_range("valid_zero_high", &s->pulses.zero_high);
    print_range("valid_one_high", &s->pulses.one_high);
    puts("END: hardware observations only; retain the USB log and GP2 trace.");
}

int main(void) {
    /* Fixed storage; no heap, new tasks, global IRQs or direct DMA control. */
    static dht22_t dht;
    static environment_record_t record;
    static validation_stats_t stats;
    stdio_init_all();
    bool ready = dht22_init(&dht, DHT_PIN);
    sleep_ms(2500); /* At least 2 seconds after boot, including RUN resets. */
    printf("DHT22 PIO validation GP2 attempts=%u clk_sys_hz=%" PRIu32
           " interval_us=%" PRIu64 " service_sleep_us=%u\n",
           (unsigned)DHT22_VALIDATION_ATTEMPTS, clock_get_hz(clk_sys),
           ATTEMPT_INTERVAL_US, SERVICE_SLEEP_US);
    puts("Observed us: driver start timestamp through service return, not exact wire time.");
    if (!ready) {
        ++stats.init_errors;
        environment_apply_dht(&record, SENSOR_RESOURCE_ERROR, 0, 0,
                              (uint32_t)(time_us_64() / 1000));
        puts("Initialization: RESOURCE ERROR; no acquisitions attempted.");
    } else {
        uint64_t next_start_us = time_us_64();
        while (stats.attempts < DHT22_VALIDATION_ATTEMPTS) {
            sleep_until(from_us_since_boot(next_start_us));
            ++stats.attempts;
            if (!dht22_start(&dht)) {
                ++stats.start_errors;
                ++stats.other;
                /* A harness start failure is separate from sensor status. */
                printf("attempt=%" PRIu32 " start=REJECTED\n", stats.attempts);
                next_start_us = time_us_64() + ATTEMPT_INTERVAL_US;
                continue;
            }
            ++stats.started;
            next_start_us = dht.started_us + ATTEMPT_INTERVAL_US;
            while (!dht22_service(&dht, &record)) sleep_us(SERVICE_SLEEP_US);
            uint64_t observed_us = time_us_64() - dht.started_us;
            bool valid = record.dht_status == SENSOR_OK &&
                         (record.validity_flags & ENV_DHT_VALID) == ENV_DHT_VALID;
            /* These are exactly the driver's completed-buffer decode outcomes.
             * A timeout may retain old/unwritten array entries: never inspect it.
             */
            bool complete = record.dht_status == SENSOR_OK ||
                            record.dht_status == SENSOR_CHECKSUM_ERROR ||
                            record.dht_status == SENSOR_PROTOCOL_ERROR ||
                            record.dht_status == SENSOR_OUT_OF_RANGE;
            switch (record.dht_status) {
            case SENSOR_OK: ++stats.ok; break;
            case SENSOR_TIMEOUT: ++stats.timeout; break;
            case SENSOR_CHECKSUM_ERROR: ++stats.checksum; break;
            case SENSOR_PROTOCOL_ERROR: ++stats.protocol; break;
            default: ++stats.other; break;
            }
            add_duration(&stats.all, observed_us);
            if (record.dht_status == SENSOR_TIMEOUT) add_duration(&stats.timed_out, observed_us);
            if (complete) {
                ++stats.complete_buffers;
                add_duration(&stats.complete, observed_us);
                add_pulses(&stats.pulses, dht.pulses, valid);
            }
            if (valid) {
                ++stats.valid;
                add_duration(&stats.valid_duration, observed_us);
            }
            /* Acquisition has ended before the first USB printf. Last numeric
             * values remain visible with their original validity and status.
             */
            printf("attempt=%" PRIu32 " start_us=%" PRIu64 " observed_us=%" PRIu64
                   " status=%s valid=%u flags=0x%02X last_temperature_x10=%d"
                   " last_humidity_x10=%u sample_ms=%" PRIu32 "\n",
                   stats.attempts, dht.started_us, observed_us,
                   environment_status_name(record.dht_status), (unsigned)valid,
                   (unsigned)record.validity_flags, (int)record.temperature_x10,
                   (unsigned)record.humidity_x10, record.dht_sample_ms);
            if (complete) {
                pulse_stats_t attempt_pulses = {0};
                add_pulses(&attempt_pulses, dht.pulses, valid);
                printf("complete_pulses response_low_us=%" PRIu32
                       " response_high_us=%" PRIu32 " bit_low_min_us=%" PRIu32
                       " bit_low_max_us=%" PRIu32 " bit_high_min_us=%" PRIu32
                       " bit_high_max_us=%" PRIu32 "\n",
                       dht.pulses[0], dht.pulses[1],
                       attempt_pulses.bit_low.minimum, attempt_pulses.bit_low.maximum,
                       attempt_pulses.bit_high.minimum, attempt_pulses.bit_high.maximum);
            } else {
                puts("complete_pulses=UNAVAILABLE (partial/stale buffer excluded)");
            }
        }
    }
    print_summary(&stats);
    while (true) sleep_ms(1000); /* Finished; reset to collect another run. */
}
