
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include "pico/stdlib.h"
#include "audio_capture.h"
#include "audio_dsp.h"

int main(void)
{
    stdio_init_all();

    audio_dsp_init();
    audio_capture_init();

    sleep_ms(2000);

    printf("\nMOSAIC Fixed-Point DSP Benchmark\n");
    printf("Sampling: 16 kHz\n");
    printf("Window: 500 ms\n");
    printf("Features: 20 (Q8)\n\n");

    uint32_t window_id = 0;
    static int32_t features[AUDIO_DSP_FEATURE_COUNT];

    while (true) {

        // Obtain a completed audio window.
        // DMA immediately starts capturing the next window.
        const uint16_t *samples =
            audio_capture_next_window();

        if (samples == NULL) {
            continue;
        }

        // Measure DSP only
        uint64_t start_us = time_us_64();

        audio_dsp_process(samples, features);

        uint64_t end_us = time_us_64();

        float dsp_ms =
            (end_us - start_us) / 1000.0f;

        float remaining_ms = 500.0f - dsp_ms;
        float overrun_ms =
            dsp_ms > 500.0f ? dsp_ms - 500.0f : 0.0f;

        window_id++;

        printf(
            "WINDOW=%lu | DSP_PROCESSING_TIME_MS=%.2f | "
            "DSP_BUDGET_LEFT_MS=%.2f | DSP_OVERRUN_MS=%.2f\n",
            (unsigned long)window_id,
            dsp_ms,
            remaining_ms,
            overrun_ms
        );

        printf(
            "RMS=%.3f | Centroid=%.1f Hz | "
            "Low=%.3f | Mid=%.3f | High=%.3f\n",
            features[0] / 256.0f,
            features[1] / 256.0f,
            features[2] / 256.0f,
            features[3] / 256.0f,
            features[4] / 256.0f
        );

        printf("FEATURES_Q8=");

        for (int i = 0; i < AUDIO_DSP_FEATURE_COUNT; i++) {
            printf(
                "%ld%s",
                (long)features[i],
                i == AUDIO_DSP_FEATURE_COUNT - 1 ? "\n" : ","
            );
        }

        printf("\n");
    }
}
