
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <inttypes.h>
#include <assert.h>
#include <string.h>
typedef unsigned int uint;
static uint64_t clock_ms;
static uint8_t input[64];
static size_t input_len, input_pos, commands;
#define CO2_UART 1
static uint64_t time_us_64(void) { return clock_ms * 1000; }
static bool uart_is_readable(int u) { (void)u; return input_pos < input_len; }
static int uart_getc(int u) { (void)u; assert(input_pos < input_len); return input[input_pos++]; }
static void uart_write_blocking(int u, const uint8_t *p, size_t n) {
    (void)u;
    const uint8_t expected[] = {0xfe,0xa6,0,1,0xa7};
    assert(n == 5 && memcmp(p, expected, 5) == 0); ++commands;
}
static void feed(const uint8_t *p, size_t n) {
    memcpy(input,p,n); input_len=n; input_pos=0;
}
#define DHT_PIN 1
#define PIR_PIN 16
#define MIC_PIN 26
#define MIC_ADC_INPUT 0
#define CO2_TX_PIN 8
#define CO2_RX_PIN 9
#define PIR_INTERVAL_MS 100
#define MIC_WINDOW_MS 50
#define DHT_INTERVAL_MS 2000
#define CO2_INTERVAL_MS 2000
#define REPORT_INTERVAL_MS 2000
#define CO2_WARMUP_MS 120000
#define CO2_TIMEOUT_MS 1000
#define MIC_QUIET_THRESHOLD 80
#define MIC_LOUD_THRESHOLD 300
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
static const char *microphone_label(uint16_t amplitude) {
    if (amplitude >= MIC_LOUD_THRESHOLD) return "LOUD";
    if (amplitude >= MIC_QUIET_THRESHOLD) return "SOUND";
    return "QUIET";
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

int main(void) {
    uint8_t good[] = {0xfe,0xa6,4,1,2,0x58,0,0,5};
    assert(validate_co2(good) == NULL);
    const size_t bad_positions[] = {0,1,2,3,8};
    for (size_t i=0;i<5;i++) {
        uint8_t bad[9]; memcpy(bad,good,9); bad[bad_positions[i]] ^= 1;
        assert(validate_co2(bad) != NULL);
    }
    uint8_t reserved[] = {0xfe,0xa6,4,1,2,0x58,1,2,8};
    assert(validate_co2(reserved) == NULL);
    assert(strcmp(microphone_label(79),"QUIET") == 0);
    assert(strcmp(microphone_label(80),"SOUND") == 0);
    assert(strcmp(microphone_label(300),"LOUD") == 0);
    sensor_data_t data = {0};
    co2_state_t state = {.next_request_ms=120000};
    clock_ms=119999; service_acd1100(&data,&state,120000);
    assert(commands==0 && !state.waiting);
    uint8_t stale[]={1,2,3}; feed(stale,3);
    clock_ms=120000; service_acd1100(&data,&state,120000);
    assert(commands==1 && state.waiting && input_pos==3);
    feed(good,4); clock_ms=120050; service_acd1100(&data,&state,120000);
    assert(state.waiting && state.received==4);
    feed(good+4,5); clock_ms=120100; service_acd1100(&data,&state,120000);
    assert(data.co2_valid && data.co2_ppm==600 && !state.waiting);
    clock_ms=121999; service_acd1100(&data,&state,120000); assert(commands==1);
    clock_ms=122000; service_acd1100(&data,&state,120000); assert(commands==2);
    clock_ms=123000; service_acd1100(&data,&state,120000);
    assert(!data.co2_valid && !state.waiting && strstr(state.error,"timeout"));
    clock_ms=124000; service_acd1100(&data,&state,120000);
    good[8]^=1; feed(good,9); clock_ms=124100; service_acd1100(&data,&state,120000);
    assert(!data.co2_valid && strcmp(state.error,"Invalid checksum")==0);
    clock_ms=126000; service_acd1100(&data,&state,120000);
    good[8]^=1; feed(good,9); clock_ms=126100; service_acd1100(&data,&state,120000);
    assert(data.co2_valid && data.co2_ppm==600 && state.error==NULL);
    puts("PASS: headers, length, command, checksums, reserved bytes, thresholds, warm-up, stale drain, fragmented UART, cadence, timeout, recovery");
}
