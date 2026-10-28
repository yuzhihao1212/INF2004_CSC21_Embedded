#ifndef MOSAIC_CLASSIFIER_PROBABILITIES_H
#define MOSAIC_CLASSIFIER_PROBABILITIES_H
#include <stdint.h>
/* Integer lookup softmax: background,speech,transient; sum exactly 32768.
 * These are model outputs, not a guarantee of probability calibration. */
void classifier_probabilities(const int32_t logits[3],uint16_t probabilities_q15[3]);
#endif
