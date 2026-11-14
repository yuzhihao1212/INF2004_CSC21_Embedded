#include "environment.h"
#include <stdio.h>
#include <string.h>

const char *environment_status_name(sensor_status_t s) {
    switch (s) {
    case SENSOR_OK: return "OK";
    case SENSOR_WARMING_UP: return "WARMING UP";
    case SENSOR_TIMEOUT: return "TIMEOUT";
    case SENSOR_CHECKSUM_ERROR: return "CHECKSUM ERROR";
    case SENSOR_OUT_OF_RANGE: return "OUT OF RANGE";
    case SENSOR_PROTOCOL_ERROR: return "PROTOCOL ERROR";
    case SENSOR_RESOURCE_ERROR: return "RESOURCE ERROR";
    default: return "STALE";
    }
}

sensor_status_t environment_decode_dht(const uint8_t b[5], int16_t *t, uint16_t *h) {
    /* Sum <= 1020 fits int; protocol checksum intentionally modulo 256. */
    if ((uint8_t)(b[0] + b[1] + b[2] + b[3]) != b[4]) return SENSOR_CHECKSUM_ERROR;
    uint16_t humidity = ((uint16_t)b[0] << 8) | b[1];
    uint16_t raw = ((uint16_t)b[2] << 8) | b[3];
    int32_t temperature = raw & 0x7fffu;
    if (raw & 0x8000u) temperature = -temperature;
    if (humidity > 1000 || temperature < -400 || temperature > 800)
        return SENSOR_OUT_OF_RANGE;
    *t = (int16_t)temperature;
    *h = humidity;
    return SENSOR_OK;
}

sensor_status_t environment_decode_dht_pulses(const uint32_t p[82], uint8_t b[5]) {
    /* PIO measurement overhead shortens each pulse by a few us. Tolerant
     * windows reject malformed pulses; 41..49 us is an ambiguous data HIGH.
     * Counts are microseconds (2 PIO cycles/count at 2 MHz), no conversion. */
    if (p[0] < 60 || p[0] > 100 || p[1] < 60 || p[1] > 100)
        return SENSOR_PROTOCOL_ERROR;
    memset(b, 0, 5);
    for (unsigned i = 0; i < 40; ++i) {
        uint32_t low = p[2 + i * 2], high = p[3 + i * 2];
        if (low < 35 || low > 70 ||
            !((high >= 15 && high <= 40) || (high >= 50 && high <= 90)))
            return SENSOR_PROTOCOL_ERROR;
        b[i / 8] = (uint8_t)((b[i / 8] << 1) | (high >= 50));
    }
    return SENSOR_OK;
}

sensor_status_t environment_decode_co2(const uint8_t b[9], uint16_t *ppm) {
    if (b[0] != 0xfe || b[1] != 0xa6 || b[2] != 4 || b[3] != 1)
        return SENSOR_PROTOCOL_ERROR;
    uint8_t sum = 0;
    /* Protocol checksum deliberately modulo 256, including reserved bytes. */
    for (unsigned i = 1; i < 8; ++i) sum = (uint8_t)(sum + b[i]);
    if (sum != b[8]) return SENSOR_CHECKSUM_ERROR;
    *ppm = ((uint16_t)b[4] << 8) | b[5];
    return SENSOR_OK;
}

void environment_apply_dht(environment_record_t *r, sensor_status_t s,
                           int16_t t, uint16_t h, uint32_t now) {
    if (s == SENSOR_OK && (t < -400 || t > 800 || h > 1000)) s = SENSOR_OUT_OF_RANGE;
    r->timestamp_ms = now;
    r->dht_status = s;
    r->validity_flags &= (uint8_t)~ENV_DHT_VALID;
    if (s == SENSOR_OK) {
        r->temperature_x10 = t; r->humidity_x10 = h;
        r->dht_sample_ms = now; r->validity_flags |= ENV_DHT_VALID;
    }
}
void environment_apply_co2(environment_record_t *r, sensor_status_t s,
                           uint16_t ppm, uint32_t now) {
    r->timestamp_ms = now; r->co2_status = s;
    r->validity_flags &= (uint8_t)~ENV_CO2_VALID;
    if (s == SENSOR_OK) {
        r->co2_ppm = ppm; r->co2_sample_ms = now; r->validity_flags |= ENV_CO2_VALID;
    }
}
void environment_apply_pir(environment_record_t *r, bool high, uint32_t now) {
    r->motion = high ? 1 : 0; r->pir_sample_ms = now; r->timestamp_ms = now;
    r->pir_status = SENSOR_OK; r->validity_flags |= ENV_PIR_VALID;
}
static bool expired(uint32_t now, uint32_t sample, uint32_t limit) {
    uint32_t age = now - sample;
    /* The upper half of the modular range denotes a future sample. */
    return age < 0x80000000u && age > limit;
}
void environment_expire(environment_record_t *r, uint32_t now) {
    r->timestamp_ms = now;
    if ((r->validity_flags & ENV_DHT_VALID) && expired(now, r->dht_sample_ms, 6000))
        environment_apply_dht(r, SENSOR_STALE, 0, 0, now);
    if ((r->validity_flags & ENV_CO2_VALID) && expired(now, r->co2_sample_ms, 5000))
        environment_apply_co2(r, SENSOR_STALE, 0, now);
    if ((r->validity_flags & ENV_PIR_VALID) && expired(now, r->pir_sample_ms, 1000)) {
        r->validity_flags &= (uint8_t)~ENV_PIR_VALID; r->pir_status = SENSOR_STALE;
    }
}
void environment_format_x10(char *out, size_t size, int16_t value) {
    int32_t magnitude = value;
    if (magnitude < 0) magnitude = -magnitude;
    snprintf(out, size, "%s%u.%u", value < 0 ? "-" : "",
             (unsigned)(magnitude / 10), (unsigned)(magnitude % 10));
}
