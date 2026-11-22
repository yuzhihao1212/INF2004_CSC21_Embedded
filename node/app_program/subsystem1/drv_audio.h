#ifndef S1_DRV_AUDIO_H
#define S1_DRV_AUDIO_H
#include "../app.h"
#include <stdint.h>
/* Init/wait called only by S1's core-0 task. Buffer valid until next wait. */
ER audio_capture_start(void);
ER audio_capture_wait(uint16_t **samples, uint64_t *timestamp);
uint64_t audio_clock_us(void);
/* Elapsed hardware time for the most recently completed 8000-sample DMA. */
uint32_t audio_capture_duration_us(void);
#endif
