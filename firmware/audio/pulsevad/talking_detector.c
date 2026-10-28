#include "talking_detector.h"
#include "talking_head.h"
#include <math.h>

float talking_head_probability(const float embedding[8]) {
    float logit = talking_head_bias;
    for (int i = 0; i < 8; ++i) logit += embedding[i] * talking_head_weights[i];
    return 1.0f / (1.0f + expf(fmaxf(-80.0f, fminf(80.0f, -logit))));
}

int talking_uses_own_head(void) { return TALKING_USE_OWN_HEAD; }

talking_event_t talking_detector_step(talking_detector_state_t *state, unsigned votes,
                                     float rms, unsigned clipped, int fault) {
    talking_event_t event;
    if (!state) return TALKING_INVALID;
    if (!isfinite(rms) || rms < 0 || votes > 3 || clipped > 8000) event = TALKING_INVALID;
    else if (fault) event = TALKING_TIMING_FAULT;
    else if (clipped >= 80) event = TALKING_CLIPPED;
    else if (rms < 4.0f) event = TALKING_LOW_LEVEL;
    else if (votes >= 2) {
        state->weak_blocks = 0;
        if (state->positive_blocks < 2) ++state->positive_blocks;
        if (state->positive_blocks >= 2) state->active = 1;
        return state->active ? TALKING_CONFIRMED : TALKING_PENDING;
    } else if (state->active && ++state->weak_blocks < 2) {
        return TALKING_CONFIRMED;
    } else event = TALKING_NO_SPEECH;
    *state = (talking_detector_state_t){0};
    return event;
}

const char *talking_event_name(talking_event_t event) {
    switch (event) {
        case TALKING_NO_SPEECH: return "NO_SPEECH";
        case TALKING_PENDING: return "SPEECH_PENDING";
        case TALKING_CONFIRMED: return "TALKING";
        case TALKING_LOW_LEVEL: return "LOW_LEVEL";
        case TALKING_CLIPPED: return "CLIPPED";
        case TALKING_TIMING_FAULT: return "TIMING_FAULT";
        default: return "INVALID_SIGNAL";
    }
}
