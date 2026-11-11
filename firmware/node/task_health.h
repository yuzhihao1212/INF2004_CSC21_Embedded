#ifndef MOSAIC_TASK_HEALTH_H
#define MOSAIC_TASK_HEALTH_H
#include <stdbool.h>
#define MOSAIC_HEALTH_NETWORK 1u
#define MOSAIC_HEALTH_ENVIRONMENT 2u
#define MOSAIC_HEALTH_AUDIO 4u
#ifdef MOSAIC_NODE_AUDIO_ENABLED
#define MOSAIC_HEALTH_REQUIRED (MOSAIC_HEALTH_NETWORK | MOSAIC_HEALTH_ENVIRONMENT | MOSAIC_HEALTH_AUDIO)
#else
#define MOSAIC_HEALTH_REQUIRED (MOSAIC_HEALTH_NETWORK | MOSAIC_HEALTH_ENVIRONMENT)
#endif
typedef struct { unsigned seen; } mosaic_task_health_t;
/* Caller synchronizes access. Consume all required progress bits atomically:
 * repeated progress from one task cannot hide a hung peer. */
static inline void mosaic_task_health_mark(mosaic_task_health_t *h, unsigned bit) {
    h->seen |= bit & MOSAIC_HEALTH_REQUIRED;
}
static inline bool mosaic_task_health_take(mosaic_task_health_t *h) {
    if ((h->seen & MOSAIC_HEALTH_REQUIRED) != MOSAIC_HEALTH_REQUIRED) return false;
    h->seen = 0;
    return true;
}
#endif
