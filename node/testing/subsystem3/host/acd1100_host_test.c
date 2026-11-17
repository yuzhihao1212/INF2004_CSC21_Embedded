#include "acd1100_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void exercise(uint32_t start)
{
    s3_acd1100_t s;
    environment_record_t r = {0};
    uint8_t frame[9] = {0xfe, 0xa6, 4, 1, 3, 0x52, 0, 0, 0};
    for (unsigned i = 1; i < 8; ++i) frame[8] += frame[i];
    s3_acd1100_init(&s, start);
    s3_acd1100_tick(&s, &r, start + 119999u);
    assert(r.co2_status == SENSOR_WARMING_UP && !s3_acd1100_due(&s, start + 119999u));
    assert(s3_acd1100_begin(&s, start + 120000u));
    assert(!s3_acd1100_begin(&s, start + 120001u));
    for (unsigned i = 0; i < 9; ++i)
        s3_acd1100_byte(&s, &r, frame[i], start + 120001u + i);
    assert(r.co2_status == SENSOR_OK && r.co2_ppm == 850 && (r.validity_flags & ENV_CO2_VALID));
    assert(!s3_acd1100_due(&s, start + 121999u));
    assert(s3_acd1100_begin(&s, start + 122000u));
    frame[8] ^= 1;
    for (unsigned i = 0; i < 9; ++i)
        s3_acd1100_byte(&s, &r, frame[i], start + 122001u + i);
    assert(r.co2_status == SENSOR_CHECKSUM_ERROR && !(r.validity_flags & ENV_CO2_VALID));
    assert(r.co2_ppm == 850);
    assert(s3_acd1100_begin(&s, start + 124000u));
    s3_acd1100_tick(&s, &r, start + 124999u);
    assert(s.waiting);
    s3_acd1100_byte(&s, &r, 0xfe, start + 125000u);
    assert(!s.waiting && r.co2_status == SENSOR_TIMEOUT);
    s3_acd1100_byte(&s, &r, 0xa6, start + 125001u);
    assert(r.co2_status == SENSOR_TIMEOUT);
    s.interval_ms = 60000;
    assert(!s3_acd1100_due(&s, start + 183999u));
    assert(s3_acd1100_due(&s, start + 184000u));
}

int main(void)
{
    const uint8_t command[5] = {0xfe, 0xa6, 0, 1, 0xa7};
    assert(memcmp(command, s3_acd1100_read_command, 5) == 0);
    exercise(0);
    exercise(UINT32_MAX - 120100u);
    puts("PASS S3-U03: ACD warm-up, cadence, checksum, timeout and rollover");
    return 0;
}
