#ifndef MOSAIC_AUDIO_HANDOFF_H
#define MOSAIC_AUDIO_HANDOFF_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "mosaic_protocol.h"

/* Pure, bounded storage. The node wraps access in its snapshot lock. Entries
 * are consecutive classified windows; explicit capture gaps clear older entries
 * because protocol v2 has one sequence for the whole two-window batch. */
typedef struct {
    mosaic_audio_window_t windows[MOSAIC_AUDIO_WINDOWS_PER_REPORT];
    uint16_t sequence, overruns;
    uint8_t count;
    uint32_t dsp_us, inference_us;
} mosaic_audio_handoff_t;

static inline void mosaic_audio_add_overruns(mosaic_audio_handoff_t *s, uint32_t n) {
    uint32_t room = UINT16_MAX - s->overruns;
    s->overruns += (uint16_t)(n < room ? n : room);
}

static inline bool mosaic_audio_publish(mosaic_audio_handoff_t *s,
        const mosaic_audio_window_t *window, uint32_t dsp_us, uint32_t inference_us) {
    if (!window || window->reserved || window->audio_class > MOSAIC_AUDIO_TRANSIENT_NOISE)
        return false;
    for (unsigned i = 0; i < MOSAIC_AUDIO_CLASS_COUNT; ++i)
        if (window->prob_pct[i] > 100) return false;
    if (s->count == MOSAIC_AUDIO_WINDOWS_PER_REPORT) {
        s->windows[0] = s->windows[1];
        s->count--;
        mosaic_audio_add_overruns(s, 1);
    }
    s->windows[s->count++] = *window;
    s->sequence++; /* Deliberate uint16 wrap matches protocol v2. */
    if (dsp_us > s->dsp_us) s->dsp_us = dsp_us;
    if (inference_us > s->inference_us) s->inference_us = inference_us;
    return true;
}

static inline void mosaic_audio_capture_dropped(mosaic_audio_handoff_t *s, uint16_t n) {
    if (!n) return;
    mosaic_audio_add_overruns(s, n);
    mosaic_audio_add_overruns(s, s->count);
    s->sequence += n;
    s->count = 0;
}

static inline void mosaic_audio_take(mosaic_audio_handoff_t *s, mosaic_telemetry_t *t) {
    memset(t->audio, 0, sizeof t->audio);
    memcpy(t->audio, s->windows, s->count * sizeof s->windows[0]);
    t->audio_window_count = s->count;
    t->audio_window_seq = s->sequence;
    t->audio_overruns = s->overruns;
    t->dsp_time_us = s->dsp_us;
    t->inference_time_us = s->inference_us;
    s->count = 0;
    s->dsp_us = s->inference_us = 0;
}
#endif
