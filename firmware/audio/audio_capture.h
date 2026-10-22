#ifndef MOSAIC_AUDIO_CAPTURE_H
#define MOSAIC_AUDIO_CAPTURE_H
#include <stdint.h>
#include "audio_dsp.h"
/* ADC0 on GP26; double buffered 16 kHz raw sample capture. */
void audio_capture_init(void);
/* Wait until a completed 500 ms window is ready, then start DMA into
 * the alternate buffer. Returned pointer is valid until the NEXT call.
 * Single consumer only; call processing before requesting the next window. */
const uint16_t *audio_capture_next_window(void);
#endif
