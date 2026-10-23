#ifndef MOSAIC_ENV_SENSORS_H
#define MOSAIC_ENV_SENSORS_H
#include "environment.h"
#include "hardware/uart.h"
typedef struct {
    uart_inst_t *uart;
    bool waiting;
    uint8_t response[9];
    size_t received;
    uint64_t deadline_ms, next_request_ms, warmup_end_ms;
    uint32_t interval_ms;  /* Between requests; 2000 by default */
} acd1100_t;
void acd1100_init(acd1100_t *s, uart_inst_t *uart, unsigned tx, unsigned rx);
void acd1100_service(acd1100_t *s, environment_record_t *r);
void environment_pir_init(unsigned pin);
void environment_pir_read(environment_record_t *r, unsigned pin);
#endif
