#ifndef MOSAIC_PULSEVAD_H
#define MOSAIC_PULSEVAD_H
#include <stdint.h>
#define PULSEVAD_SAMPLES 3200
#define PULSEVAD_MELS 64
#define PULSEVAD_FRAMES 21
#define PULSEVAD_EMBEDDING 8
typedef struct {
    uint32_t frontend_us;
    uint32_t network_us;
    uint32_t prep_us;
    uint32_t spectral_us;
    uint32_t normalization_us;
} pulsevad_profile_t;
/* Measured for the latest context on Pico; zero in host numeric builds. */
const pulsevad_profile_t *pulsevad_last_profile(void);
/* Idempotent; on Pico reserves/launches core 1 for the frontend worker.
 * Call before audio capture. All public VAD APIs have a single caller on core 0.
 */
void pulsevad_init(void);
/* Static workspaces: single caller only. Waveform range is nominally [-1,1]. */
void pulsevad_frontend(const float waveform[PULSEVAD_SAMPLES], float features[64 * 21]);
void pulsevad_predict(const float features[64 * 21], float embedding[8], float logits[2]);
/* ADC must be unsigned 12-bit. Removes window DC, scales by 2048, then infers. */
float pulsevad_process_adc(const uint16_t samples[3200], float embedding[8]);
#endif
