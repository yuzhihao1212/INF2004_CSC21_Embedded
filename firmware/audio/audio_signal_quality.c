#include "audio_signal_quality.h"

static uint32_t integer_sqrt(uint64_t value) {
    uint64_t bit = (uint64_t)1 << 62, result = 0;
    while (bit > value) bit >>= 2;
    while (bit) {
        if (value >= result + bit) {
            value -= result + bit;
            result = (result >> 1) + bit;
        } else result >>= 1;
        bit >>= 2;
    }
    return (uint32_t)result;
}

int audio_signal_quality(const uint16_t *samples, size_t count,
                         audio_signal_quality_t *out) {
    if (!samples || !out || !count || count > 8000) return 0;
    audio_signal_quality_t q = {4095, 0, 0, 0, 0};
    uint64_t sum = 0;
    for (size_t i = 0; i < count; ++i) {
        uint16_t sample = samples[i];
        if (sample > 4095) return 0;
        if (sample < q.minimum) q.minimum = sample;
        if (sample > q.maximum) q.maximum = sample;
        if (sample <= 4 || sample >= 4091) ++q.clipped_samples;
        sum += sample;
    }
    q.mean_q8 = (uint32_t)((sum * 256) / count);
    uint64_t energy = 0;
    for (size_t i = 0; i < count; ++i) {
        int64_t centered = (int64_t)samples[i] * 256 - q.mean_q8;
        energy += (uint64_t)(centered * centered);
    }
    q.ac_rms_q8 = integer_sqrt(energy / count);
    *out = q;
    return 1;
}

const char *audio_signal_status(const audio_signal_quality_t *q,
                               size_t count, const int32_t features_q8[20]) {
    if (!q || !features_q8 || !count || count > 8000) return "INVALID";
    /* >=1% samples near either rail is a clipping warning. */
    if (q->clipped_samples * 100u >= count) return "NEAR_ADC_RAIL";
    /* Raw AC RMS <4 ADC counts plus broadband-looking spectral summary.
     * This flags a weak noise-like input; it does not diagnose wiring. */
    if (q->ac_rms_q8 < 4u * 256u) {
        if (features_q8[1] > 3000 * 256 && features_q8[4] > 166)
            return "LOW_LEVEL_BROADBAND";
        return "LOW_LEVEL";
    }
    return "CHECK_SPEECH_QUALITY";
}
