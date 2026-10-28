#ifndef MOSAIC_AUDIO_RAW_DIAGNOSTIC_H
#define MOSAIC_AUDIO_RAW_DIAGNOSTIC_H
#include <stddef.h>
#include <stdint.h>
#define AUDIO_RAW_DIAGNOSTIC_BLOCKS 16
/* Diagnostic framing only. ADC values are preserved exactly as 3-digit hex. */
int audio_raw_diagnostic_emit(const uint16_t samples[8000], uint32_t window,
                             uint64_t delivered_us, float pulse, float own,
                             void (*write)(const char *, size_t));
#endif
