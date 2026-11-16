#include "audio_inference.h"
#include "dsp_int8_candidate.h"
#include "classifier_probabilities.h"
classifier_event_t classify_audio(classifier_timing_state_t *state,
    const audio_features_t *in,uint64_t now,mosaic_audio_window_t *out)
{
    if (!state || !in || !out) return CLASSIFIER_INVALID;
    int32_t logits[3]; uint16_t p[3];
    int best=dsp_int8_predict(in->features,logits);
    classifier_probabilities(logits,p);
    int fault=in->timing_fault || now<in->captured_us || now-in->captured_us>500000;
    classifier_event_t event=classifier_timing_step(state,(unsigned)best,p,
        in->rms_q8,in->clipped,fault,in->captured_us);
    *out=(mosaic_audio_window_t){0};
    /* Wire RMS is mean filtered frame RMS, Q8 -> Q4; raw AC RMS gates quality. */
    int32_t rms=in->features[0];
    out->rms_x16=(uint16_t)(rms<=0?0:rms>1048560?65535:(rms+8)/16);
    out->prob_pct[0]=(uint8_t)((uint32_t)p[0]*100/32768);
    out->prob_pct[1]=(uint8_t)((uint32_t)p[1]*100/32768);
    out->prob_pct[3]=(uint8_t)(100-out->prob_pct[0]-out->prob_pct[1]);
    static const uint8_t ids[]={MOSAIC_AUDIO_BACKGROUND_NOISE,
        MOSAIC_AUDIO_SPEECH,MOSAIC_AUDIO_TRANSIENT_NOISE};
    if (best>=0 && best<3 && event!=CLASSIFIER_INVALID && event!=CLASSIFIER_CLIPPED
        && event!=CLASSIFIER_LOW_LEVEL && event!=CLASSIFIER_TIMING_FAULT
        && (uint32_t)p[best]*100>=in->threshold_pct*32768)
        out->audio_class=ids[best];
    return event;
}
