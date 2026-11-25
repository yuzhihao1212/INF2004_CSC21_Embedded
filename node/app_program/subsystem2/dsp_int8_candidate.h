#ifndef DSP_INT8_CANDIDATE_H
#define DSP_INT8_CANDIDATE_H
#include <stdint.h>
/* The deployed int8 classifier: a 20-16-3 fully connected network with
 * int8 weights and integer-only arithmetic (the file keeps its original
 * "candidate" name from model selection).
 * Input is subsystem 1's 20 mean/std features in signed Q8; the feature
 * front end was host-verified against Moe's integer DSP.
 * Writes the three raw logits and returns the winning class:
 * 0 background, 1 speech, 2 transient; -1 for a null argument. */
int dsp_int8_predict(const int32_t features_q8[20], int32_t logits[3]);
#endif
