#include "s3_telemetry.h"
#include "s5_protocol.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    environment_record_t r = {0};
    s5_state_t s;
    mosaic_telemetry_packet_t p;
    s5_init(&s, 1);
    environment_apply_dht(&r, SENSOR_OK, -34, 672, 100);
    environment_apply_co2(&r, SENSOR_WARMING_UP, 0, 100);
    environment_apply_pir(&r, true, 100);
    uint8_t flags = s3_environment_wire_flags(&r);
    assert(flags == (MOSAIC_VALID_TEMP_HUM | MOSAIC_VALID_CO2_WARMUP));
    s5_update_environment(&s, r.temperature_x10, r.humidity_x10, r.co2_ppm, flags, 100);
    s5_update_pir(&s, 10, 3);
    s5_build_telemetry(&s, 100, &p);
    assert(p.payload.temperature_x10 == -34 && p.payload.humidity_x10 == 672);
    assert(p.payload.valid_flags == (flags | MOSAIC_VALID_PIR));
    assert(p.payload.pir_active_pct == 30);
    environment_apply_co2(&r, SENSOR_OK, 850, 101);
    environment_apply_dht(&r, SENSOR_CHECKSUM_ERROR, 0, 0, 101);
    flags = s3_environment_wire_flags(&r);
    assert(flags == MOSAIC_VALID_CO2);
    s5_update_environment(&s, r.temperature_x10, r.humidity_x10, r.co2_ppm, flags, 101);
    s5_build_telemetry(&s, 101, &p);
    assert(p.payload.valid_flags == MOSAIC_VALID_CO2 && p.payload.co2_ppm == 850);
    assert(p.payload.temperature_x10 == 0 && p.payload.humidity_x10 == 0);
    s5_build_telemetry(&s, 6102, &p);
    assert(!(p.payload.valid_flags & MOSAIC_VALID_CO2));
    r.validity_flags = ENV_TEMP_VALID;
    assert(s3_environment_wire_flags(&r) == 0);
    puts("PASS S3-U04: S3 flags and fixed-point values through S5 telemetry");
    return 0;
}
