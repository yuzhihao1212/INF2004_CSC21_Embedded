#ifndef S3_DRV_DHT22_H
#define S3_DRV_DHT22_H
#include "environment.h"
typedef struct {
    void *pio;
    unsigned sm, offset;
    int dma;
    bool ready, active, stopping;
    uint32_t started_ms;
    sensor_status_t result;
    uint32_t pulses[82]; /* Permanent task-owned DMA buffer. */
} s3_dht_t;
bool s3_dht_init(s3_dht_t *d);
bool s3_dht_start(s3_dht_t *d, uint32_t now);
void s3_dht_service(s3_dht_t *d, environment_record_t *r, uint32_t now);
/* Hardware boundary, used by deterministic tests. No IRQ callbacks. */
bool s3_dht_hw_init(s3_dht_t *d);
void s3_dht_hw_start(s3_dht_t *d);
int s3_dht_hw_result(s3_dht_t *d); /* 0 busy, 1 complete, -1 DMA error */
void s3_dht_hw_stop(s3_dht_t *d);
bool s3_dht_hw_stopped(s3_dht_t *d);
#endif
