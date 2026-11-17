#ifndef S3_ENVIRONMENT_SERVICE_H
#define S3_ENVIRONMENT_SERVICE_H
#include "drv_dht22.h"
#include "drv_acd1100.h"
#include "../../../firmware/common/include/mosaic_protocol.h"
typedef struct {
    environment_record_t record;
    s3_dht_t dht;
    s3_co2_driver_t co2;
    mosaic_config_t config;
    uint32_t boot_ms, dht_ms, pir_ms, config_ms, post_ms, pir_batch_ms;
    uint32_t pir_samples, pir_active, pir_dropped, s5_errors, bad_configs;
    int32_t config_result, environment_result, pir_result;
    bool pir_ready, dht_initialized, dht_attempted, powered;
} s3_service_t;
/* All calls, including hardware init, belong to environment_task only. */
void s3_service_init(s3_service_t *s, uint32_t now);
void s3_service_step(s3_service_t *s, uint32_t now, bool pio_available);
void s3_service_start_due(s3_service_t *s, uint32_t fresh_now);
#endif
