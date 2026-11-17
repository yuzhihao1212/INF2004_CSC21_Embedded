
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include "pico/stdlib.h"
#include "audio_capture.h"
#include "audio_dsp.h"

static void print_q8(const char *name, int32_t value)
{
    int64_t magnitude=value;
    if (magnitude<0) magnitude=-magnitude;
    uint32_t scaled=(uint32_t)((magnitude*1000+128)/256);
    printf("%s=%s%lu.%03lu",name,value<0?"-":"",
        (unsigned long)(scaled/1000),(unsigned long)(scaled%1000));
}

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

        uint64_t dsp_us=end_us-start_us;
        uint64_t remaining=dsp_us<500000?500000-dsp_us:0;
        uint64_t overrun=dsp_us>500000?dsp_us-500000:0;
        ++window_id;
        printf("WINDOW=%lu | DSP_PROCESSING_TIME_MS=%lu.%03lu | DSP_BUDGET_LEFT_MS=%lu.%03lu | DSP_OVERRUN_MS=%lu.%03lu\n",
            (unsigned long)window_id,(unsigned long)(dsp_us/1000),(unsigned long)(dsp_us%1000),
            (unsigned long)(remaining/1000),(unsigned long)(remaining%1000),
            (unsigned long)(overrun/1000),(unsigned long)(overrun%1000));
        print_q8("RMS",features[0]); printf(" | ");
        print_q8("Centroid",features[1]); printf(" Hz | ");
        print_q8("Low",features[2]); printf(" | ");
        print_q8("Mid",features[3]); printf(" | ");
        print_q8("High",features[4]); printf("\n");

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
