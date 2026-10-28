/* Trained by train_talking_head.py. Frozen PulseVAD backbone, local logistic head. */

#ifndef MOSAIC_TALKING_HEAD_H
#define MOSAIC_TALKING_HEAD_H

#define TALKING_USE_OWN_HEAD 0

static const float talking_head_weights[8] = {
    -0.780527443f, -0.720755163f, 5.03244131f, -0.99791163f, -0.715189567f, -0.860532774f, -0.316553665f, -0.671224403f,
};

static const float talking_head_bias = -2.4154349f;

#endif
