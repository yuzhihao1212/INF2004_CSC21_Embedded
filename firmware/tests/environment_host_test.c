/* Pure logic only: no simulated claim of PIO, DMA, GPIO or UART execution. */
#include "environment.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void frame(uint8_t b[5], uint16_t humidity, uint16_t temperature) {
    b[0] = (uint8_t)(humidity >> 8); b[1] = (uint8_t)humidity;
    b[2] = (uint8_t)(temperature >> 8); b[3] = (uint8_t)temperature;
    b[4] = (uint8_t)(b[0] + b[1] + b[2] + b[3]);
}
static void test_decode(void) {
    uint8_t b[5]; int16_t t = 123; uint16_t h = 456;
    frame(b, 672, 258);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OK && t == 258 && h == 672);
    frame(b, 672, 0x8022);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OK && t == -34);
    b[4] ^= 1;
    assert(environment_decode_dht(b, &t, &h) == SENSOR_CHECKSUM_ERROR && t == -34 && h == 672);
    frame(b, 1001, 258);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OUT_OF_RANGE);
    frame(b, 500, 801);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OUT_OF_RANGE);
    frame(b, 500, 0x8191);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OUT_OF_RANGE);
    frame(b, 1000, 800);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OK && t == 800 && h == 1000);
    frame(b, 0, 0x8190);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OK && t == -400 && h == 0);
    frame(b, 65535, 0xffff);
    assert(environment_decode_dht(b, &t, &h) == SENSOR_OUT_OF_RANGE);

    uint8_t co2[9] = {0xfe, 0xa6, 4, 1, 3, 0x52, 0, 0, 0};
    for (unsigned i = 1; i < 8; ++i) co2[8] = (uint8_t)(co2[8] + co2[i]);
    uint16_t ppm = 0;
    assert(environment_decode_co2(co2, &ppm) == SENSOR_OK && ppm == 850);
    co2[8] ^= 1;
    assert(environment_decode_co2(co2, &ppm) == SENSOR_CHECKSUM_ERROR && ppm == 850);
    co2[0] = 0;
    assert(environment_decode_co2(co2, &ppm) == SENSOR_PROTOCOL_ERROR);
}
static void test_pulses(void) {
    uint8_t b[5], decoded[5]; uint32_t p[82] = {78, 78};
    frame(b, 672, 258);
    for (unsigned i = 0; i < 40; ++i) {
        p[2 + i * 2] = 48;
        p[3 + i * 2] = b[i / 8] & (1u << (7 - i % 8)) ? 68 : 25;
    }
    assert(environment_decode_dht_pulses(p, decoded) == SENSOR_OK);
    assert(memcmp(b, decoded, 5) == 0);
    p[3] = 45;
    assert(environment_decode_dht_pulses(p, decoded) == SENSOR_PROTOCOL_ERROR);
    p[3] = UINT32_MAX;
    assert(environment_decode_dht_pulses(p, decoded) == SENSOR_PROTOCOL_ERROR);
    p[0] = 0;
    assert(environment_decode_dht_pulses(p, decoded) == SENSOR_PROTOCOL_ERROR);
}
static void test_format(void) {
    const int16_t input[] = {258, -34, 672, -1, 0, INT16_MIN, INT16_MAX};
    const char *expected[] = {"25.8", "-3.4", "67.2", "-0.1", "0.0", "-3276.8", "3276.7"};
    for (unsigned i = 0; i < sizeof(input) / sizeof(input[0]); ++i) {
        char out[8]; environment_format_x10(out, sizeof(out), input[i]);
        assert(strcmp(out, expected[i]) == 0);
    }
    char small[3]; environment_format_x10(small, sizeof(small), 258);
    assert(small[2] == '\0');
}
static void test_status(void) {
    environment_record_t r = {0};
    environment_apply_dht(&r, SENSOR_OK, 258, 672, 100);
    environment_apply_co2(&r, SENSOR_OK, 850, 100);
    environment_apply_pir(&r, true, 100);
    assert(r.validity_flags == 15 && r.motion == 1);
    environment_apply_dht(&r, SENSOR_TIMEOUT, 0, 0, 110);
    assert(r.validity_flags == (ENV_CO2_VALID | ENV_PIR_VALID));
    assert(r.temperature_x10 == 258 && r.humidity_x10 == 672 && r.dht_status == SENSOR_TIMEOUT);
    assert(r.timestamp_ms == 110 && r.dht_sample_ms == 100);
    environment_apply_dht(&r, SENSOR_CHECKSUM_ERROR, 0, 0, 111);
    assert(r.validity_flags == (ENV_CO2_VALID | ENV_PIR_VALID));
    environment_apply_dht(&r, SENSOR_PROTOCOL_ERROR, 0, 0, 112);
    assert(r.validity_flags == (ENV_CO2_VALID | ENV_PIR_VALID));
    environment_apply_dht(&r, SENSOR_OK, -34, 500, 120);
    assert(r.validity_flags == 15 && r.dht_status == SENSOR_OK && r.dht_sample_ms == 120);
    environment_apply_co2(&r, SENSOR_WARMING_UP, 0, 120);
    assert(r.validity_flags == (ENV_DHT_VALID | ENV_PIR_VALID));
    assert(r.co2_status == SENSOR_WARMING_UP && r.co2_ppm == 850);
    environment_apply_co2(&r, SENSOR_TIMEOUT, 0, 130);
    assert(r.validity_flags == (ENV_DHT_VALID | ENV_PIR_VALID));
    environment_apply_pir(&r, false, 130);
    assert(r.motion == 0);
    environment_apply_dht(&r, SENSOR_OK, 801, 500, 140);
    assert(!(r.validity_flags & ENV_DHT_VALID) && r.dht_status == SENSOR_OUT_OF_RANGE);
    environment_apply_dht(&r, SENSOR_OK, 258, 672, UINT32_MAX - 100);
    environment_apply_co2(&r, SENSOR_OK, 850, UINT32_MAX - 100);
    environment_apply_pir(&r, true, UINT32_MAX - 100);
    environment_expire(&r, 50);
    assert(r.validity_flags == 15); // 151 ms elapsed across wrap
    environment_expire(&r, 7000);
    assert(r.validity_flags == 0 && r.dht_status == SENSOR_STALE && r.co2_status == SENSOR_STALE);
    assert(r.temperature_x10 == 258 && r.co2_ppm == 850);
}
int main(void) {
    test_decode(); test_pulses(); test_format(); test_status();
    puts("PASS: DHT/CO2 decode, pulse validation, integer formatting, validity/status and wrap/stale logic");
    return 0;
}
