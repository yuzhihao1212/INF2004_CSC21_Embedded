#ifndef MOSAIC_AUDIO_DSP_H
#define MOSAIC_AUDIO_DSP_H
#include <stdint.h>
#define AUDIO_DSP_SAMPLE_RATE 16000
#define AUDIO_DSP_WINDOW_SAMPLES 8000
#define AUDIO_DSP_FEATURE_COUNT 20
#define AUDIO_DSP_Q_BITS 8
/* [0..9] mean; [10..19] std of RMS, centroid, low/mid/high, MFCC1..5. */
/* Input: 8000 consecutive unsigned 12-bit ADC samples at 16 kHz. */
/* Output: 20 signed int32 features in Q8 (divide by 256 to display). */
/* Caller must serialize access: one DSP processing invocation at a time. */
void audio_dsp_init(void);
void audio_dsp_process(const uint16_t samples[AUDIO_DSP_WINDOW_SAMPLES],
                       int32_t out_q8[AUDIO_DSP_FEATURE_COUNT]);
#endif
