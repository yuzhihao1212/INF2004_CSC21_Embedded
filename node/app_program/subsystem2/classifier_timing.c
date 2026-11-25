/*
 *  classifier_timing.c
 *  Subsystem 2 -- window gates and speech persistence (rules in the header).
 *
 *  Pure logic with no kernel or hardware calls, so the same file is
 *  compiled and tested on the host.
 */
#include "classifier_timing.h"
#include <stddef.h>

static classifier_event_t clear(classifier_timing_state_t *state,classifier_event_t event) {
    if (state) *state=(classifier_timing_state_t){0};
    return event;
}

classifier_event_t classifier_timing_step(classifier_timing_state_t *state,
    unsigned predicted_class,const uint16_t p[3],uint32_t rms_q8,
    unsigned clipped_samples,int timing_fault,uint64_t window_us) {
    if (!state) return CLASSIFIER_INVALID;
    if (!p || predicted_class>2 || clipped_samples>8000 || rms_q8>4095u*256u)
        return clear(state,CLASSIFIER_INVALID);
    if (p[0]>32768 || p[1]>32768 || p[2]>32768 || (unsigned)p[0]+p[1]+p[2]!=32768)
        return clear(state,CLASSIFIER_INVALID);
    if (timing_fault || (state->have_previous && window_us<=state->last_window_us))
        return clear(state,CLASSIFIER_TIMING_FAULT);
    /* Clipped: 80 of 8000 samples (1%) at an ADC rail. */
    if (clipped_samples>=80) return clear(state,CLASSIFIER_CLIPPED);
    /* Too quiet to classify: AC RMS below 4 ADC counts (Q8). */
    if (rms_q8<4u*256u) return clear(state,CLASSIFIER_LOW_LEVEL);
    /* More than 1.5 windows since the last one: not consecutive. */
    if (state->have_previous && window_us-state->last_window_us>750000)
        *state=(classifier_timing_state_t){0};
    state->have_previous=1;state->last_window_us=window_us;
    if (predicted_class==2) {
        state->positive_windows=state->weak_windows=state->active=0;
        return CLASSIFIER_TRANSIENT;
    }
    /* Speech wins with P(speech) >= 0.5 (16384 in Q15). */
    if (predicted_class==1 && p[1]>=16384) {
        state->weak_windows=0;
        if (state->positive_windows<2) ++state->positive_windows;
        if (state->positive_windows>=2) state->active=1;
        return state->active ? CLASSIFIER_TALKING : CLASSIFIER_PENDING;
    }
    /* One weak window is held as talking; the second one ends the event. */
    if (state->active && ++state->weak_windows<2) return CLASSIFIER_TALKING;
    state->positive_windows=state->weak_windows=state->active=0;
    return CLASSIFIER_NO_SPEECH;
}

const char *classifier_event_name(classifier_event_t event) {
    switch(event) {
        case CLASSIFIER_NO_SPEECH:return "NO_SPEECH";
        case CLASSIFIER_PENDING:return "SPEECH_PENDING";
        case CLASSIFIER_TALKING:return "TALKING";
        case CLASSIFIER_TRANSIENT:return "TRANSIENT";
        case CLASSIFIER_LOW_LEVEL:return "LOW_LEVEL";
        case CLASSIFIER_CLIPPED:return "CLIPPED";
        case CLASSIFIER_TIMING_FAULT:return "TIMING_FAULT";
        default:return "INVALID_SIGNAL";
    }
}
