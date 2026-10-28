#ifndef MOSAIC_AUDIO_SIGNAL_QUALITY_H
#define MOSAIC_AUDIO_SIGNAL_QUALITY_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint16_t minimum, maximum;
    uint32_t mean_q8, ac_rms_q8, clipped_samples;
} audio_signal_quality_t;

/* Raw 12-bit ADC window; 1..8000 samples. Returns 0 for invalid calls.
 * RMS is AC ADC counts in Q8, not calibrated SPL or microphone SNR. */
int audio_signal_quality(const uint16_t *samples, size_t count,
                         audio_signal_quality_t *out);
/* Illustrative diagnostic thresholds, not a calibrated speech detector. */
const char *audio_signal_status(const audio_signal_quality_t *quality,
                               size_t count, const int32_t features_q8[20]);
#endif
