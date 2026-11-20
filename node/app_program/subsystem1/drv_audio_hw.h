#ifndef S1_DRV_AUDIO_HW_H
#define S1_DRV_AUDIO_HW_H
#include <stdint.h>
/* SDK hardware calls only. S1 retains ownership; the kernel owns the IRQ. */
int s1_audio_hw_init(void);
void s1_audio_hw_start(unsigned channel, uint16_t *destination);
void s1_audio_hw_stop(void);
void s1_audio_hw_release(unsigned channel);
#endif
