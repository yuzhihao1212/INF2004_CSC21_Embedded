#ifndef DSP_INT8_CANDIDATE_H
#define DSP_INT8_CANDIDATE_H
#include <stdint.h>
/* Candidate: feature frontend host-verified against current Moe integer DSP.
 * Input is the 20 mean/std features in signed Q8. No firmware replacement yet.
 * Classes: 0 background, 1 speech, 2 transient. */
int dsp_int8_predict(const int32_t features_q8[20], int32_t logits[3]);
#endif
