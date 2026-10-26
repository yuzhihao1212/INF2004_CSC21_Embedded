#ifndef MOSAIC_DHT22_H
#define MOSAIC_DHT22_H
#include "environment.h"
#include "hardware/pio.h"
typedef struct {
    PIO pio;
    int sm, dma;
    unsigned offset, pin;
    bool ready, active;
    uint64_t started_us;
    uint32_t pulses[82];
} dht22_t;
/* One owned SM/program and DMA channel; no IRQ or global interrupt lock.
 * Initialize once from the single-threaded startup path. Claims are retained
 * for the instance/program lifetime; per-read cleanup stops, not unclaims,
 * these resources. The SDK DMA abort waits only for in-flight bus transfers,
 * never for sensor edges. The caller must not reinitialize a live instance.
 * Call service regularly; timeout is observed on the first call after 10 ms.
 * Start no sooner than 2 s after power-on and at least 2 s between attempts.
 * Resource exhaustion returns false instead of panic/stealing another owner. */
bool dht22_init(dht22_t *d, unsigned pin);
bool dht22_start(dht22_t *d);
bool dht22_service(dht22_t *d, environment_record_t *r);
#endif
