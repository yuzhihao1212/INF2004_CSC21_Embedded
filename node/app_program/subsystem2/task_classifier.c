#include "../subsystem5/subsystem5.h"
#include "subsystem2.h"
#include "audio_inference.h"
#include "../subsystem1/drv_audio.h"
void classifier_task(INT stacd,void *exinf)
{
    (void)stacd; (void)exinf;
    classifier_timing_state_t state={0};
    uint32_t previous=0, dropped=0, logged=0;
    for (;;) {
        audio_features_t in; mosaic_audio_window_t out;
        INT size=tk_rcv_mbf(mbf_audio_features,&in,TMO_FEVR);
        if (size!=sizeof in) { state=(classifier_timing_state_t){0}; continue; }
        uint32_t distance=in.sequence-previous;
        previous=in.sequence;
        if (distance!=1) {
            state=(classifier_timing_state_t){0};
            if (distance>1) dropped+=distance-1;
        }
        uint64_t start=audio_clock_us();
        classifier_event_t event=classify_audio(&state,&in,start,&out);
        uint64_t end=audio_clock_us();
        if (end-in.captured_us>500000) {
            out.audio_class=MOSAIC_AUDIO_UNKNOWN;
            state=(classifier_timing_state_t){0}; event=CLASSIFIER_TIMING_FAULT;
        }
        /* S2 is the sole audio poster, preserving loss/result ordering. */
        if (dropped) {
            uint16_t batch=dropped>65535?65535:(uint16_t)dropped;
            if (s5_audio_dropped(batch)!=E_OK) { ++dropped; continue; }
            dropped-=batch;
            if (dropped) { ++dropped; continue; }
        }
        if (s5_post_audio_window(&out,in.dsp_us,(uint32_t)(end-start))!=E_OK) {
            ++dropped; state=(classifier_timing_state_t){0};
        }
        if (++logged%4==0)
            tm_printf((UB*)"audio seq=%u class=%u p=%u/%u/%u event=%s dsp_us=%u ml_us=%u\n",
                in.sequence,out.audio_class,out.prob_pct[0],out.prob_pct[1],out.prob_pct[3],
                classifier_event_name(event),in.dsp_us,(uint32_t)(end-start));
    }
}
