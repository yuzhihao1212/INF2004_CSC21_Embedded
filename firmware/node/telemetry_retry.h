#ifndef MOSAIC_TELEMETRY_RETRY_H
#define MOSAIC_TELEMETRY_RETRY_H

#include <stdbool.h>
#include <stdint.h>
#include "mosaic_protocol.h"

#define MOSAIC_RETRY_SLOTS 4u
#define MOSAIC_RETRY_FIRST_MS 100u
#define MOSAIC_RETRY_SPACING_MS 200u
#define MOSAIC_RETRY_LIFETIME_MS 600u

typedef struct {
    mosaic_telemetry_packet_t packet;
    uint64_t due_ms, expires_ms;
    uint8_t attempts;
    bool active;
} mosaic_retry_slot_t;

typedef struct {
    mosaic_retry_slot_t slots[MOSAIC_RETRY_SLOTS];
    uint32_t overflow, expired;
} mosaic_retry_queue_t;

/* Main-loop only. Copies own their data; no pbuf pointers or heap storage. */
static inline bool mosaic_retry_add(mosaic_retry_queue_t *q,
                                    const mosaic_telemetry_packet_t *packet,
                                    uint64_t now_ms) {
    for (unsigned i = 0; i < MOSAIC_RETRY_SLOTS; ++i) {
        mosaic_retry_slot_t *s = &q->slots[i];
        if (s->active && now_ms >= s->expires_ms) {
            s->active = false;
            q->expired++;
        }
        if (!s->active) {
            *s = (mosaic_retry_slot_t){.packet = *packet,
                .due_ms = now_ms + MOSAIC_RETRY_FIRST_MS,
                .expires_ms = now_ms + MOSAIC_RETRY_LIFETIME_MS, .active = true};
            return true;
        }
    }
    q->overflow++;
    return false;
}

static inline bool mosaic_retry_take(mosaic_retry_queue_t *q, uint64_t now_ms,
                                     mosaic_telemetry_packet_t *packet) {
    mosaic_retry_slot_t *next = NULL;
    for (unsigned i = 0; i < MOSAIC_RETRY_SLOTS; ++i) {
        mosaic_retry_slot_t *s = &q->slots[i];
        if (s->active && now_ms >= s->expires_ms) {
            s->active = false;
            q->expired++;
        }
        if (s->active && now_ms >= s->due_ms && (!next || s->due_ms < next->due_ms))
            next = s;
    }
    if (!next) return false;
    *packet = next->packet; /* Same seq, sample timestamp and payload. */
    if (++next->attempts == 2)
        next->active = false;
    else
        next->due_ms = now_ms + MOSAIC_RETRY_SPACING_MS;
    return true;
}

#endif
