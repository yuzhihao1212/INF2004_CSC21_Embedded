#ifndef S3_ACD1100_PROTOCOL_H
#define S3_ACD1100_PROTOCOL_H

#include "environment.h"

/* Transport-independent state. The future UART owner must discard old RX
 * bytes before starting a request and must send the entire five-byte command
 * without interleaving. All times are monotonic modulo 2^32 milliseconds;
 * calls and deadlines must be less than 2^31 ms apart. */
typedef struct {
    uint32_t started_ms, request_ms, last_attempt_ms, interval_ms;
    uint8_t response[9];
    unsigned received;
    bool waiting, attempted, warmed;
} s3_acd1100_t;

extern const uint8_t s3_acd1100_read_command[5];
void s3_acd1100_init(s3_acd1100_t *s, uint32_t now);
bool s3_acd1100_due(const s3_acd1100_t *s, uint32_t now);
bool s3_acd1100_begin(s3_acd1100_t *s, uint32_t now);
void s3_acd1100_byte(s3_acd1100_t *s, environment_record_t *r,
                     uint8_t byte, uint32_t now);
void s3_acd1100_tick(s3_acd1100_t *s, environment_record_t *r, uint32_t now);

#endif
