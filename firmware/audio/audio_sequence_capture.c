#include <stdio.h>
#include <inttypes.h>
#include "pico/stdlib.h"
#include "audio_capture.h"
#include "audio_dsp.h"
#include "audio_signal_quality.h"

/* Separate capture firmware: preserves spectral frames and energy over time.
 * USB CDC baud is virtual. Printing can block when the host is not consuming;
 * delivery timestamps allow the host to detect pauses. Not a classifier. */
int main(void) {
    stdio_init_all();
    audio_dsp_init();
    sleep_ms(2000);
    audio_capture_init();
    static int16_t mel[AUDIO_DSP_SEQUENCE_FRAMES][AUDIO_DSP_MEL_BANDS];
    static int32_t rms[AUDIO_DSP_SEQUENCE_FRAMES];
    static int32_t summary[AUDIO_DSP_FEATURE_COUNT];
    uint32_t window = 0;
    while (true) {
        const uint16_t *samples = audio_capture_next_window();
        uint64_t delivered_us = time_us_64();
        if (!samples) continue;
        audio_signal_quality_t quality;
        if (!audio_signal_quality(samples, AUDIO_DSP_WINDOW_SAMPLES, &quality)) continue;
        uint64_t start = time_us_64();
        if (!audio_dsp_process_sequence(samples, summary, mel, rms)) continue;
        uint64_t dsp_us = time_us_64()-start;
        ++window;
        printf("SEQ_BEGIN,1,%" PRIu32 ",%" PRIu64 ",%d,%d,%u,%u,%" PRIu32
               ",%" PRIu32 ",%" PRIu32 ",%" PRIu64 "\n",
               window, delivered_us, AUDIO_DSP_SEQUENCE_FRAMES, AUDIO_DSP_MEL_BANDS,
               (unsigned int)quality.minimum, (unsigned int)quality.maximum,
               quality.mean_q8, quality.ac_rms_q8, quality.clipped_samples, dsp_us);
        for (int frame=0; frame<AUDIO_DSP_SEQUENCE_FRAMES; ++frame) {
            printf("SEQ_FRAME,%" PRIu32 ",%d,%" PRId32, window, frame, rms[frame]);
            for (int band=0; band<AUDIO_DSP_MEL_BANDS; ++band)
                printf(",%d", (int)mel[frame][band]);
            printf("\n");
        }
        printf("SEQ_SUMMARY,%" PRIu32, window);
        for (int feature=0; feature<AUDIO_DSP_FEATURE_COUNT; ++feature)
            printf(",%" PRId32, summary[feature]);
        printf("\nSEQ_END,%" PRIu32 "\n", window);
    }
}
