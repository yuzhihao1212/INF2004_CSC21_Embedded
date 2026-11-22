/* Focused adapter check: model scores are controlled; real timing code runs. */
#include "../../app_program/subsystem2/audio_inference.h"
#include <assert.h>
#include <stdio.h>
static unsigned winner=1;
static uint16_t scores[3]={2000,30000,768};
int dsp_int8_predict(const int32_t features[20],int32_t logits[3])
{ (void)features; (void)logits; return (int)winner; }
void classifier_probabilities(const int32_t logits[3],uint16_t out[3])
{ (void)logits; for(int i=0;i<3;i++) out[i]=scores[i]; }
int main(void)
{
    classifier_timing_state_t state={0};
    audio_features_t input={.rms_q8=2560,.threshold_pct=60};
    mosaic_audio_window_t out;
    input.captured_us=500000;
    assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_PENDING);
    assert(out.audio_class==MOSAIC_AUDIO_UNKNOWN);
    unsigned raw=out.prob_pct[1];
    input.captured_us+=500000;
    assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_TALKING);
    assert(out.audio_class==MOSAIC_AUDIO_SPEECH && out.prob_pct[1]==raw);
    winner=0; scores[0]=30000; scores[1]=2000;
    input.captured_us+=500000;
    assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_TALKING);
    assert(out.audio_class==MOSAIC_AUDIO_SPEECH);
    input.captured_us+=500000;
    assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_NO_SPEECH);
    assert(out.audio_class==MOSAIC_AUDIO_BACKGROUND_NOISE);
    winner=1; scores[0]=8000; scores[1]=24000; input.threshold_pct=80;
    for(int i=0;i<3;i++) {
        input.captured_us+=500000;
        assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_NO_SPEECH);
        assert(out.audio_class==MOSAIC_AUDIO_UNKNOWN);
    }
    winner=2; scores[0]=2000; scores[1]=768; scores[2]=30000;
    input.captured_us+=500000;
    assert(classify_audio(&state,&input,input.captured_us,&out)==CLASSIFIER_TRANSIENT);
    assert(out.audio_class==MOSAIC_AUDIO_TRANSIENT_NOISE);
    puts("S2-U07 PASS: pending, onset, hold, release, threshold, transient, raw scores");
}
