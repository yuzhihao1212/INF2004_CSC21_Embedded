#ifndef MOSAIC_AUDIO_STREAM_H
#define MOSAIC_AUDIO_STREAM_H
#include <stddef.h>
#include <stdint.h>
/* Lossless paired little-endian 12-bit samples: 8000 samples = 12000 bytes. */
int audio_stream_emit(const uint16_t samples[8000], uint32_t window,
                      uint64_t delivered_us, void (*write)(const char *, size_t));
#endif
