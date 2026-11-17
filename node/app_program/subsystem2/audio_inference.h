#ifndef S2_AUDIO_INFERENCE_H
#define S2_AUDIO_INFERENCE_H
#include "../../../firmware/common/include/mosaic_protocol.h"
#include "../subsystem1/audio_features.h"
#include "classifier_timing.h"
classifier_event_t classify_audio(classifier_timing_state_t *state,
    const audio_features_t *input,uint64_t now,mosaic_audio_window_t *output);
#endif
