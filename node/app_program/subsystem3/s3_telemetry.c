#include "s3_telemetry.h"
#include "../../../firmware/common/include/mosaic_protocol.h"

uint8_t s3_environment_wire_flags(const environment_record_t *r)
{
    uint8_t flags = 0;
    if ((r->validity_flags & ENV_DHT_VALID) == ENV_DHT_VALID)
        flags |= MOSAIC_VALID_TEMP_HUM;
    if (r->validity_flags & ENV_CO2_VALID) flags |= MOSAIC_VALID_CO2;
    else if (r->co2_status == SENSOR_WARMING_UP) flags |= MOSAIC_VALID_CO2_WARMUP;
    return flags;
}
