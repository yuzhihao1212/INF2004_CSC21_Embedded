/* Own integer classifier + local timing. Reference comparison belongs to PC fusion. */
#include <stdbool.h>
#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/stdio.h"
#include "pico/stdio_usb.h"
#include "audio_capture.h"
#include "audio_dsp.h"
#include "audio_signal_quality.h"
#include "classifier/dsp_int8_candidate.h"
#include "classifier/classifier_probabilities.h"
#include "classifier_timing.h"

int main(void) {
    stdio_init_all();
    stdio_set_translate_crlf(&stdio_usb,false);
    sleep_ms(2000);
    puts("MOSAIC OWN_INT8_CLASSIFIER int8-timing-v1; GP26 ADC0,16kHz");
    puts("Classes=background,speech,transient; onset=2 windows; weak hold=1; transient veto=immediate");
    puts("TALKING means local sustained speech, not confirmed student identity.");
    audio_dsp_init();audio_capture_init();
    classifier_timing_state_t timing={0};
    uint32_t window=0;
    static const char *classes[]={"BACKGROUND","SPEECH","TRANSIENT"};
    while (true) {
        const uint16_t *adc=audio_capture_next_window();
        if (!adc) continue;
        uint64_t delivered=time_us_64();++window;
        audio_signal_quality_t quality;
        if (!audio_signal_quality(adc,8000,&quality)) {
            timing=(classifier_timing_state_t){0};
            puts("AUDIO,EVENT=INVALID_SIGNAL,MODEL=OWN_INT8_CLASSIFIER,BUILD=int8-timing-v1");continue;
        }
        int32_t features[20],logits[3];uint16_t probability[3];
        audio_dsp_process(adc,features);
        int predicted=dsp_int8_predict(features,logits);
        classifier_probabilities(logits,probability);
        uint64_t processing=time_us_64()-delivered;
        uint64_t work=time_us_64()-delivered;
        bool overrun=work>500000;
        classifier_event_t event=classifier_timing_step(&timing,(unsigned)predicted,
            probability,quality.ac_rms_q8,quality.clipped_samples,overrun,delivered);
        uint32_t rms100=(quality.ac_rms_q8*100u+128)/256u;
        printf("AUDIO,WINDOW=%lu,DELIVERED_US=%llu,RMS_ADC=%lu.%02lu,"
               "RAW_CLASS=%s,P_BACKGROUND_Q15=%u,P_SPEECH_Q15=%u,P_TRANSIENT_Q15=%u,"
               "EVENT=%s,ONSET_WINDOWS=%u,HOLD=%u,PROCESSING_US=%llu,WORK_US=%llu,"
               "OVERRUN=%u,ADC_NEAR_RAIL=%lu,MODEL=OWN_INT8_CLASSIFIER,BUILD=int8-timing-v1\n",
               (unsigned long)window,(unsigned long long)delivered,
               (unsigned long)(rms100/100),(unsigned long)(rms100%100),
               predicted>=0 && predicted<3 ? classes[predicted] : "INVALID",
               probability[0],probability[1],probability[2],classifier_event_name(event),
               timing.positive_windows,(unsigned)(timing.active && timing.weak_windows),
               (unsigned long long)processing,(unsigned long long)work,
               (unsigned)overrun,(unsigned long)quality.clipped_samples);
    }
}
