/* Compile the original and migrated C implementations in separate objects. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../app_program/subsystem1/audio_dsp.h"
#include "../../app_program/subsystem2/audio_inference.h"
#include "../../app_program/subsystem2/dsp_int8_candidate.h"
#include "../../app_program/subsystem2/classifier_probabilities.h"
void reference_init(void);
void reference_process(const uint16_t *,int32_t *);
int reference_predict(const int32_t *,int32_t *);
void reference_probabilities(const int32_t *,uint16_t *);
int main(void)
{
    uint16_t samples[8000]; int32_t a[20],b[20],la[3],lb[3];
    uint16_t pa[3],pb[3]; unsigned rng=42;
    reference_init(); audio_dsp_init();
    for (unsigned test=0;test<32;++test) {
        for (unsigned i=0;i<8000;++i) {
            rng=rng*1664525u+1013904223u;
            samples[i]=test==0?2048:test==1?0:test==2?4095:
                test==3?(i%2?0:4095):(uint16_t)(rng>>20);
        }
        reference_process(samples,a); audio_dsp_process(samples,b);
        assert(!memcmp(a,b,sizeof a));
        assert(reference_predict(a,la)==dsp_int8_predict(b,lb));
        assert(!memcmp(la,lb,sizeof la));
        reference_probabilities(la,pa); classifier_probabilities(lb,pb);
        assert(!memcmp(pa,pb,sizeof pa));
        audio_features_t in={0}; in.captured_us=500000; in.sequence=1;
        in.rms_q8=2560; memcpy(in.features,b,sizeof b);
        classifier_timing_state_t state={0}; mosaic_audio_window_t out;
        classify_audio(&state,&in,500001,&out);
        static const int wire[]={1,2,4};
        int best=dsp_int8_predict(b,lb);
        assert(out.audio_class==wire[best]); assert(out.prob_pct[2]==0);
        assert(out.prob_pct[0]+out.prob_pct[1]+out.prob_pct[3]==100);
        in.features[0]=2560; state=(classifier_timing_state_t){0};
        classify_audio(&state,&in,500001,&out); assert(out.rms_x16==160);
        in.clipped=80;
        assert(classify_audio(&state,&in,500001,&out)==CLASSIFIER_CLIPPED);
        assert(out.audio_class==0);
        in.clipped=0; in.rms_q8=0;
        assert(classify_audio(&state,&in,500001,&out)==CLASSIFIER_LOW_LEVEL);
        assert(out.audio_class==0);
        in.rms_q8=2560;
        assert(classify_audio(&state,&in,1000001,&out)==CLASSIFIER_TIMING_FAULT);
        assert(out.audio_class==0);
        in.threshold_pct=101;
        classify_audio(&state,&in,500001,&out); assert(out.audio_class==0);
    }
    /* Verify persistence itself independently of model predictions. */
    classifier_timing_state_t state={0}; uint16_t speech[3]={0,32768,0};
    assert(classifier_timing_step(&state,1,speech,2560,0,0,500000)==CLASSIFIER_PENDING);
    assert(classifier_timing_step(&state,1,speech,2560,0,0,1000000)==CLASSIFIER_TALKING);
    uint16_t transient[3]={0,0,32768};
    assert(classifier_timing_step(&state,2,transient,2560,0,0,1500000)==CLASSIFIER_TRANSIENT);
    puts("S1-U04 PASS: 32 windows, all 20 DSP features identical");
    puts("S2-U03 PASS: original/ported logits, classes and Q15 probabilities identical");
    puts("S2-U04 PASS: protocol class IDs, Q4 RMS, reserved slot, probability sum");
    puts("S2-U05 PASS: clipping, low level, stale/threshold gates and persistence");
    return 0;
}
