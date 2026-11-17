#include "acd1100_protocol.h"

const uint8_t s3_acd1100_read_command[5] = {0xfe, 0xa6, 0, 1, 0xa7};

/* A future time has an age in the upper half of the unsigned range. */
static bool elapsed(uint32_t now, uint32_t then, uint32_t duration)
{
    uint32_t age = now - then;
    return age < UINT32_C(0x80000000) && age >= duration;
}

void s3_acd1100_init(s3_acd1100_t *s, uint32_t now)
{
    *s = (s3_acd1100_t){.started_ms = now, .interval_ms = 2000};
}

bool s3_acd1100_due(const s3_acd1100_t *s, uint32_t now)
{
    return !s->waiting && (s->warmed || elapsed(now, s->started_ms, 120000)) &&
        (!s->attempted || elapsed(now, s->last_attempt_ms, s->interval_ms));
}

bool s3_acd1100_begin(s3_acd1100_t *s, uint32_t now)
{
    if (!s3_acd1100_due(s, now)) return false;
    s->warmed = true;
    s->waiting = true;
    s->attempted = true;
    s->request_ms = s->last_attempt_ms = now;
    s->received = 0;
    return true;
}

void s3_acd1100_tick(s3_acd1100_t *s, environment_record_t *r, uint32_t now)
{
    if (elapsed(now, s->started_ms, 120000)) s->warmed = true;
    if (!s->warmed) {
        environment_apply_co2(r, SENSOR_WARMING_UP, 0, now);
    } else if (s->waiting && elapsed(now, s->request_ms, 1000)) {
        s->waiting = false;
        environment_apply_co2(r, SENSOR_TIMEOUT, 0, now);
    }
}

void s3_acd1100_byte(s3_acd1100_t *s, environment_record_t *r,
                     uint8_t byte, uint32_t now)
{
    s3_acd1100_tick(s, r, now);
    if (!s->waiting) return;
    s->response[s->received++] = byte;
    if (s->received == sizeof s->response) {
        uint16_t ppm = 0;
        sensor_status_t status = environment_decode_co2(s->response, &ppm);
        s->waiting = false;
        environment_apply_co2(r, status, ppm, now);
    }
}
