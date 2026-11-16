#ifndef S1_AUDIO_FEATURES_H
#define S1_AUDIO_FEATURES_H
#include <stdint.h>
/* Value copied into S2's message buffer; no raw-buffer pointers. */
typedef struct {
    uint64_t captured_us;
    uint32_t sequence, dsp_us, rms_q8, clipped, timing_fault, threshold_pct;
    int32_t features[20];
} audio_features_t;
#endif
