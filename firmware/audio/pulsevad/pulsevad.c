/* MOSAIC implementation of pinned PulseVAD: Q24 FFT and FP32 mel/CNN.
 * Upstream architecture/weights: vendor/SOURCE.json and vendor/LICENSE.
 * No heap, Python, ONNX runtime or TensorFlow runtime on the board.
 */
#include "pulsevad.h"
#include "vendor/pulsevad_model.h"
#include "vendor/pulsevad_tables.h"
#include <math.h>
#include <stddef.h>
#ifdef PICO_ON_DEVICE
#include "pico/time.h"
#include "pico/multicore.h"
#include "hardware/sync.h"
#elif defined(PULSEVAD_HOST_PARALLEL)
#include <pthread.h>
#include <stdlib.h>
#endif

static float waveform[3200], normalized[3200], features[64 * 21];
/* Q24, stage-scaled FFT: avoid software floating point in 48,384 butterflies
 * per context. Waveform z-normalisation bounds |x| <= sqrt(3199) < 57;
 * 2 * 57 * 2^24 < INT32_MAX, including pre-shift butterfly additions.
 * Q30 twiddles retain weak-band precision; products/sums fit int64_t.
 */
typedef struct {
    int32_t re[512], im[512];
    float power[257];
} fft_workspace_t;
static fft_workspace_t fft_workspace[2];
static int32_t fft_cos[256], fft_sin[256];
static int fft_initialized;
#ifdef PICO_ON_DEVICE
static int worker_started;
#define PULSEVAD_WORKER_READY 0x50564331u
#endif
static pulsevad_profile_t profile;

const pulsevad_profile_t *pulsevad_last_profile(void) { return &profile; }
static float a[12 * 21], b[12 * 21], residual[8 * 21], branch[8 * 21];

static void fft(fft_workspace_t *workspace) {
    int32_t *re = workspace->re, *im = workspace->im;
    for (unsigned i = 1, j = 0; i < 512; ++i) {
        unsigned bit = 256;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            int32_t t = re[i]; re[i] = re[j]; re[j] = t;
            t = im[i]; im[i] = im[j]; im[j] = t;
        }
    }
    for (unsigned length = 2; length <= 512; length *= 2) {
        unsigned half = length / 2, step = 512 / length;
        for (unsigned start = 0; start < 512; start += length) {
            for (unsigned j = 0; j < half; ++j) {
                unsigned i = start + j, k = i + half, w = j * step;
                int32_t vr, vi;
                if (w == 0) { vr = re[k]; vi = im[k]; }
                else if (w == 128) { vr = im[k]; vi = -re[k]; }
                else {
                    vr = (int32_t)(((int64_t)re[k] * fft_cos[w] +
                                    (int64_t)im[k] * fft_sin[w]) >> 30);
                    vi = (int32_t)(((int64_t)im[k] * fft_cos[w] -
                                    (int64_t)re[k] * fft_sin[w]) >> 30);
                }
                int32_t ur = re[i], ui = im[i];
                re[i] = (ur + vr) / 2; im[i] = (ui + vi) / 2;
                re[k] = (ur - vr) / 2; im[k] = (ui - vi) / 2;
            }
        }
    }
}

/* Only the frame index differs between cores. Normalised waveform/tables are
 * read-only until both workers finish. Each frame has disjoint output cells.
 */
static void compute_frames(float *output, int first, int last, fft_workspace_t *workspace) {
    int32_t *re = workspace->re, *im = workspace->im;
    float *power = workspace->power;
    for (int frame = first; frame < last; ++frame) {
        for (int j = 0; j < 512; ++j) re[j] = im[j] = 0;
        for (int j = 0; j < 400; ++j) {
            int index = frame * 160 + j - 200;
            if (index < 0) index = -index;
            if (index >= 3200) index = 6398 - index;
            re[56 + j] = (int32_t)(normalized[index] * pv_hann[j] * 16777216.0f);
        }
        fft(workspace);
        for (int j = 0; j < 257; ++j) {
            /* Restore FFT's 1/512 stage scale before power/mel/EPS. */
            float real = re[j] * (1.0f / 32768.0f);
            float imag = im[j] * (1.0f / 32768.0f);
            power[j] = real * real + imag * imag;
        }
        for (int band = 0; band < 64; ++band) {
            float energy = 0.0f;
            for (int j = 0; j < pv_mel_count[band]; ++j)
                energy += power[pv_mel_start[band] + j] * pv_mel_coeff[pv_mel_offset[band] + j];
            output[band * 21 + frame] = logf(energy + 1e-5f);
        }
    }
}

#ifdef PICO_ON_DEVICE
static void frontend_worker(void) {
    multicore_fifo_push_blocking(PULSEVAD_WORKER_READY);
    while (1) {
        float *output = (float *)(uintptr_t)multicore_fifo_pop_blocking();
        __dmb();
        compute_frames(output, 11, 21, &fft_workspace[1]);
        __dmb();
        multicore_fifo_push_blocking(PULSEVAD_WORKER_READY);
    }
}
#elif defined(PULSEVAD_HOST_PARALLEL)
/* Host regression mode: run the exact two ranges concurrently to catch
 * accidentally shared FFT scratch or overlapping output writes.
 */
static void *frontend_worker(void *output) {
    compute_frames((float *)output, 11, 21, &fft_workspace[1]);
    return NULL;
}
#endif

void pulsevad_init(void) {
    if (!fft_initialized) {
        for (int i = 0; i < 256; ++i) {
            fft_cos[i] = (int32_t)(pv_cos[i] * 1073741824.0f);
            fft_sin[i] = (int32_t)(pv_sin[i] * 1073741824.0f);
        }
        fft_initialized = 1;
    }
#ifdef PICO_ON_DEVICE
    /* audio_talking owns core 1. Call public VAD APIs from core 0 only. */
    if (!worker_started) {
        multicore_launch_core1(frontend_worker);
        hard_assert(multicore_fifo_pop_blocking() == PULSEVAD_WORKER_READY);
        worker_started = 1;
    }
#endif
}

void pulsevad_frontend(const float *input, float *output) {
    pulsevad_init();
#ifdef PICO_ON_DEVICE
    uint64_t prep_started = time_us_64();
#endif
    float mean = 0.0f;
    for (int i = 0; i < 3200; ++i) {
        normalized[i] = input[i] - (i ? 0.97f * input[i-1] : 0.0f);
        mean += normalized[i];
    }
    mean /= 3200.0f;
    float variance = 0.0f;
    for (int i = 0; i < 3200; ++i) {
        float x = normalized[i] - mean;
        variance += x * x;
    }
    float reciprocal = 1.0f / (sqrtf(variance / 3200.0f) + 1e-5f);
    for (int i = 0; i < 3200; ++i) normalized[i] = (normalized[i] - mean) * reciprocal;
#ifdef PICO_ON_DEVICE
    uint64_t spectral_started = time_us_64();
    profile.prep_us = (uint32_t)(spectral_started - prep_started);
    __dmb();
    multicore_fifo_push_blocking((uint32_t)(uintptr_t)output);
    compute_frames(output, 0, 11, &fft_workspace[0]);
    hard_assert(multicore_fifo_pop_blocking() == PULSEVAD_WORKER_READY);
    __dmb();
    uint64_t normalization_started = time_us_64();
    profile.spectral_us = (uint32_t)(normalization_started - spectral_started);
#elif defined(PULSEVAD_HOST_PARALLEL)
    pthread_t worker;
    if (pthread_create(&worker, NULL, frontend_worker, output)) abort();
    compute_frames(output, 0, 11, &fft_workspace[0]);
    if (pthread_join(worker, NULL)) abort();
#else
    /* Exercise the same two ranges/workspaces in host numeric verification. */
    compute_frames(output, 0, 11, &fft_workspace[0]);
    compute_frames(output, 11, 21, &fft_workspace[1]);
#endif
    for (int band = 0; band < 64; ++band) {
        float sum = 0.0f, var = 0.0f;
        float origin = output[band * 21];
        for (int t = 0; t < 21; ++t) sum += output[band * 21 + t] - origin;
        float avg = origin + sum / 21.0f;
        for (int t = 0; t < 21; ++t) {
            float v = output[band * 21 + t] - avg;
            var += v * v;
        }
        float reciprocal_scale = 1.0f / (sqrtf(var / 21.0f) + 1e-5f);
        for (int t = 0; t < 21; ++t) output[band * 21 + t] = (output[band * 21 + t] - avg) * reciprocal_scale;
    }
#ifdef PICO_ON_DEVICE
    profile.normalization_us = (uint32_t)(time_us_64() - normalization_started);
#endif
}

static void conv(const float *x, float *y, const float *w, const float *bias,
                 int inputs, int outputs, int kernel, int dilation, int depthwise, int relu) {
    if (kernel == 1) {
        /* All dense convolutions are 1x1. Avoid generic kernel/padding work
         * in every MAC; preserve channel accumulation order exactly.
         */
        for (int o = 0; o < outputs; ++o) {
            for (int t = 0; t < 21; ++t) {
                float sum = bias ? bias[o] : 0.0f;
                for (int c = 0; c < inputs; ++c) sum += x[c * 21 + t] * w[o * inputs + c];
                y[o * 21 + t] = relu && sum < 0.0f ? 0.0f : sum;
            }
        }
        return;
    }
    int pad = dilation * (kernel - 1) / 2;
    if (depthwise) {
        /* Padding is implicit. For the wide dilated conv most original
         * iterations visited zeros; traverse only the supported kernel span.
         */
        for (int o = 0; o < outputs; ++o) {
            for (int t = 0; t < 21; ++t) {
                int first = pad > t ? (dilation == 1 ? pad-t : (pad-t+1)/2) : 0;
                int last = dilation == 1 ? 21+pad-t : (20+pad-t)/2+1;
                if (last > kernel) last = kernel;
                float sum = bias ? bias[o] : 0.0f;
                for (int k = first; k < last; ++k)
                    sum += x[o * 21 + t + k * dilation - pad] * w[o * kernel + k];
                y[o * 21 + t] = relu && sum < 0.0f ? 0.0f : sum;
            }
        }
        return;
    }
    for (int o = 0; o < outputs; ++o) {
        for (int t = 0; t < 21; ++t) {
            float sum = bias ? bias[o] : 0.0f;
            int first = depthwise ? o : 0, last = depthwise ? o+1 : inputs;
            for (int c = first; c < last; ++c) {
                for (int k = 0; k < kernel; ++k) {
                    int time = t + k * dilation - pad;
                    if (time >= 0 && time < 21) {
                        int wi = depthwise ? o * kernel + k : (o * inputs + c) * kernel + k;
                        sum += x[c * 21 + time] * w[wi];
                    }
                }
            }
            y[o * 21 + t] = relu && sum < 0.0f ? 0.0f : sum;
        }
    }
}

void pulsevad_predict(const float *x, float *embedding, float *logits) {
    conv(x, a, pv_adapter_weight, pv_adapter_bias, 64, 12, 1, 1, 0, 1);
    conv(a, b, pv_conv0_dw_weight, NULL, 12, 12, 11, 1, 1, 0);
    conv(b, a, pv_conv0_pw_weight, pv_conv0_pw_bias, 12, 8, 1, 1, 0, 1);
    conv(a, b, pv_block1_weight, pv_block1_bias, 8, 8, 1, 1, 0, 1);
    conv(b, residual, pv_block2_weight, pv_block2_bias, 8, 8, 1, 1, 0, 1);
    conv(residual, a, pv_subA_dw_weight, NULL, 8, 8, 17, 1, 1, 0);
    conv(a, b, pv_subA_pw_weight, pv_subA_pw_bias, 8, 8, 1, 1, 0, 1);
    conv(b, a, pv_subC_dw_weight, NULL, 8, 8, 17, 1, 1, 0);
    conv(a, branch, pv_subC_pw_weight, pv_subC_pw_bias, 8, 8, 1, 1, 0, 0);
    conv(residual, b, pv_skip_weight, pv_skip_bias, 8, 8, 1, 1, 0, 0);
    for (int i = 0; i < 8 * 21; ++i) a[i] = fmaxf(0.0f, branch[i] + b[i]);
    conv(a, b, pv_conv4_dw_weight, NULL, 8, 8, 29, 2, 1, 0);
    conv(b, a, pv_conv4_pw_weight, pv_conv4_pw_bias, 8, 8, 1, 1, 0, 1);
    conv(a, b, pv_conv5_weight, pv_conv5_bias, 8, 8, 1, 1, 0, 1);
    for (int c = 0; c < 8; ++c) {
        float sum = 0.0f;
        for (int t = 0; t < 21; ++t) sum += b[c * 21 + t];
        embedding[c] = sum / 21.0f;
    }
    for (int c = 0; c < 2; ++c) {
        logits[c] = pv_classifier_bias[c];
        for (int j = 0; j < 8; ++j) logits[c] += pv_classifier_weight[c * 8 + j] * embedding[j];
    }
}

float pulsevad_process_adc(const uint16_t *samples, float *embedding) {
#ifdef PICO_ON_DEVICE
    uint64_t started = time_us_64();
#endif
    float mean = 0.0f, logits[2];
    for (int i = 0; i < 3200; ++i) mean += samples[i];
    mean /= 3200.0f;
    for (int i = 0; i < 3200; ++i) waveform[i] = ((float)samples[i] - mean) / 2048.0f;
    pulsevad_frontend(waveform, features);
#ifdef PICO_ON_DEVICE
    uint64_t frontend_done = time_us_64();
    profile.frontend_us = (uint32_t)(frontend_done - started);
#endif
    pulsevad_predict(features, embedding, logits);
#ifdef PICO_ON_DEVICE
    profile.network_us = (uint32_t)(time_us_64() - frontend_done);
#endif
    return 1.0f / (1.0f + expf(fmaxf(-80.0f, fminf(80.0f, logits[0] - logits[1]))));
}
