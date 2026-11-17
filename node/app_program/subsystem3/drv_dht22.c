#include "drv_dht22.h"
#include "s3_time.h"

bool s3_dht_init(s3_dht_t *d)
{
    *d = (s3_dht_t){.dma = -1};
    d->ready = s3_dht_hw_init(d);
    return d->ready;
}

bool s3_dht_start(s3_dht_t *d, uint32_t now)
{
    if (!d->ready || d->active) return false;
    d->started_ms = now;
    d->active = true;
    s3_dht_hw_start(d);
    return true;
}

void s3_dht_service(s3_dht_t *d, environment_record_t *r, uint32_t now)
{
    if (!d->active) return;
    if (!d->stopping) {
        int result = s3_dht_hw_result(d);
        if (!result && !s3_elapsed(now, d->started_ms, 10)) return;
        d->result = result > 0 ? SENSOR_OK : result < 0 ? SENSOR_RESOURCE_ERROR : SENSOR_TIMEOUT;
        s3_dht_hw_stop(d);
        d->stopping = true;
    }
    /* DMA abort may still have an in-flight bus transfer. Never spin or reuse
     * the buffer/channel until it retires; the other sensors keep running. */
    if (!s3_dht_hw_stopped(d)) {
        environment_apply_dht(r, SENSOR_RESOURCE_ERROR, 0, 0, now);
        return;
    }
    uint8_t bytes[5];
    int16_t temperature = 0;
    uint16_t humidity = 0;
    sensor_status_t result = d->result;
    if (result == SENSOR_OK) {
        result = environment_decode_dht_pulses(d->pulses, bytes);
        if (result == SENSOR_OK) result = environment_decode_dht(bytes, &temperature, &humidity);
    }
    environment_apply_dht(r, result, temperature, humidity, now);
    if (result == SENSOR_OK) r->dht_sample_ms = d->started_ms;
    d->active = d->stopping = false;
}
