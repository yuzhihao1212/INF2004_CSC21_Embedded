/* Local speech evidence and optional paired-node reference comparison service. */
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/stdio.h"
#include "pico/stdio_usb.h"
#include "audio_capture.h"
#include "audio_stream.h"
#include "reference_service.h"
#include "audio_raw_diagnostic.h"
#include "audio_signal_quality.h"
#include "pulsevad/pulsevad.h"
#include "pulsevad/talking_detector.h"

static void diagnostic_write(const char *data, size_t count) {
    fwrite(data, 1, count, stdout);
    fflush(stdout);
}

int main(void) {
    stdio_init_all();
    /* Binary PCM must not have 0x0a bytes expanded to CRLF by stdio. */
    stdio_set_translate_crlf(&stdio_usb, false);
    sleep_ms(2000);
    puts("MOSAIC PulseVAD timing-v7 (lecturer baseline + WAV stream); GP26 ADC0, 16 kHz");
    puts("TALKING means local speech evidence, not confirmed student conversation.");
    printf("DECISION_MODEL=%s | MIN_RMS_ADC=4 | POSITIVE_BLOCKS_REQUIRED=2 | RELEASE_WEAK_BLOCKS=2\n",
           talking_uses_own_head() ? "OWN_TRAINED_HEAD" : "PRETRAINED_PULSEVAD");
    pulsevad_init();
    audio_capture_init();
    uint32_t window = 0;
    talking_detector_state_t detector = {0};
    unsigned raw_remaining = 0;
    bool streaming = false;
    uint64_t previous_delivery = 0;
    while (true) {
        int command;
        while ((command = getchar_timeout_us(0)) >= 0) {
            if (command=='@' || reference_service_receiving()) {
                reference_service_feed(command,diagnostic_write);
            } else if (command == 'r') {
                streaming = false;
                raw_remaining = AUDIO_RAW_DIAGNOSTIC_BLOCKS;
                detector = (talking_detector_state_t){0};
                previous_delivery = 0;
                puts("RAW_READY,16");
            } else if (command == 's') {
                streaming = true;
                raw_remaining = 0;
                detector = (talking_detector_state_t){0};
                previous_delivery = 0;
                puts("STREAM_READY,1");
            } else if (command == 'v') {
                streaming = false;
                raw_remaining = 0;
                detector = (talking_detector_state_t){0};
                previous_delivery = 0;
                puts("RAW_DONE");
                puts("STREAM_DONE");
            }
        }
        const uint16_t *samples = audio_capture_next_window();
        if (!samples) continue;
        uint64_t delivered = time_us_64(), start = delivered;
        bool gap = previous_delivery && (delivered - previous_delivery > 750000);
        previous_delivery = delivered;
        ++window;
        audio_signal_quality_t quality;
        if (!audio_signal_quality(samples, 8000, &quality)) {
            detector = (talking_detector_state_t){0};
            puts("EVENT=INVALID_SIGNAL");
            continue;
        }
        if (raw_remaining) {
            /* Diagnostic mode compares ONE exact 200 ms context on board/PC.
             * No VAD events or inference timing claims during raw transport.
             */
            float embedding[8];
            float pulse = pulsevad_process_adc(samples, embedding);
            float own = talking_head_probability(embedding);
            audio_raw_diagnostic_emit(samples, window, delivered, pulse, own, diagnostic_write);
            detector = (talking_detector_state_t){0};
            previous_delivery = 0;
            if (!--raw_remaining) puts("RAW_DONE");
            continue;
        }
        float rms = quality.ac_rms_q8 / 256.0f;
        float pulse_sum = 0, own_sum = 0;
        uint32_t frontend_us = 0, network_us = 0;
        uint32_t prep_us = 0, spectral_us = 0, normalization_us = 0;
        unsigned votes = 0;
        /* Three overlapping 200 ms contexts cover the complete 500 ms buffer.
         * They are not three independent observations and not a 600 ms duration.
         */
        for (int offset = 0; offset <= 4800; offset += 2400) {
            float embedding[8];
            float pulse = pulsevad_process_adc(samples + offset, embedding);
            const pulsevad_profile_t *profile = pulsevad_last_profile();
            frontend_us += profile->frontend_us;
            network_us += profile->network_us;
            prep_us += profile->prep_us;
            spectral_us += profile->spectral_us;
            normalization_us += profile->normalization_us;
            float own = talking_head_probability(embedding);
            pulse_sum += pulse; own_sum += own;
            if ((talking_uses_own_head() ? own : pulse) >= 0.5f) ++votes;
        }
        uint64_t processing = time_us_64() - start;
        uint64_t transmit_started = time_us_64();
        if (streaming) audio_stream_emit(samples, window, delivered, diagnostic_write);
        uint64_t transmit_us = time_us_64() - transmit_started;
        uint64_t work_us = time_us_64() - start;
        bool overrun = work_us > 500000;
        const char *event = talking_event_name(talking_detector_step(
            &detector, votes, rms, quality.clipped_samples, overrun || gap));
        printf("VAD,WINDOW=%lu,DELIVERED_US=%llu,RMS_ADC=%.2f,"
               "PULSE_PROB=%.4f,OWN_PROB=%.4f,SPEECH_VOTES=%u,"
               "EVENT=%s,PROCESSING_US=%llu,OVERRUN=%u,ADC_NEAR_RAIL=%lu,"
               "FRONTEND_US=%lu,NETWORK_US=%lu,PREP_US=%lu,"
               "FFT_MEL_US=%lu,ZNORM_US=%lu,HOLD=%u,TX_US=%llu,WORK_US=%llu,BUILD=timing-v7\n",
               (unsigned long)window, (unsigned long long)delivered, rms,
               pulse_sum/3.0f, own_sum/3.0f, votes, event,
               (unsigned long long)processing, (unsigned)overrun,
               (unsigned long)quality.clipped_samples,
               (unsigned long)frontend_us, (unsigned long)network_us,
               (unsigned long)prep_us, (unsigned long)spectral_us,
               (unsigned long)normalization_us,
               (unsigned)(detector.active && detector.weak_blocks),
               (unsigned long long)transmit_us, (unsigned long long)work_us);
    }
}
