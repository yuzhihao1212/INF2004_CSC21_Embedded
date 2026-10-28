#ifndef MOSAIC_AUDIO_DSP_H
#define MOSAIC_AUDIO_DSP_H
#include <stdint.h>
#define AUDIO_DSP_SAMPLE_RATE 16000
#define AUDIO_DSP_WINDOW_SAMPLES 8000
#define AUDIO_DSP_FEATURE_COUNT 20
#define AUDIO_DSP_Q_BITS 8
#define AUDIO_DSP_SEQUENCE_FRAMES 48
#define AUDIO_DSP_MEL_BANDS 20
#define AUDIO_DSP_FRAME_SAMPLES 400
#define AUDIO_DSP_HOP_SAMPLES 160
/* [0..9] mean; [10..19] std of RMS, centroid, low/mid/high, MFCC1..5. */
/* Input: 8000 consecutive unsigned 12-bit ADC samples at 16 kHz. */
/* Output: 20 signed int32 features in Q8 (divide by 256 to display). */
/* Caller must serialize access: one DSP processing invocation at a time. */
void audio_dsp_init(void);
void audio_dsp_process(const uint16_t samples[AUDIO_DSP_WINDOW_SAMPLES],
                       int32_t out_q8[AUDIO_DSP_FEATURE_COUNT]);
/* Same DSP/summary, additionally preserves the time sequence. All pointers
 * required; returns 0 on invalid pointers, 1 on success. Init first.
 * Mel output: natural log energies in signed Q8, silence floor -24*256.
 * The existing FFT normalizes each frame independently; retain frame RMS
 * separately to preserve absolute energy information. Frames start at samples
 * 0,160,...,7520 within each 8000-sample window (not 50 frames per window).
 * No shared outputs are retained; caller supplies all buffers. */
int audio_dsp_process_sequence(
    const uint16_t samples[AUDIO_DSP_WINDOW_SAMPLES],
    int32_t summary_q8[AUDIO_DSP_FEATURE_COUNT],
    int16_t mel_q8[AUDIO_DSP_SEQUENCE_FRAMES][AUDIO_DSP_MEL_BANDS],
    int32_t frame_rms_q8[AUDIO_DSP_SEQUENCE_FRAMES]);
#endif
