#include "audio_dsp.h"
#include <stdint.h>
#include <math.h>
#include <limits.h>
/* Pure DSP: no GPIO, ADC, DMA, multicore, printf or timing calls. */
// audio configuration
#define SAMPLE_RATE 16000

// 500 ms classification window
#define AUDIO_SAMPLES 8000

// 25 ms frame at 16 kHz
#define FRAME_SIZE 400

// keep the original 10 ms hop to retain the existing feature definitions
#define HOP_SIZE 160

// floor((8000 - 400) / 160) + 1 = 48 frames
#define NUM_FRAMES 48

#define FFT_SIZE 512
#define FFT_BINS ((FFT_SIZE / 2) + 1)

// frequency band
#define MIN_FREQ 125.0f
#define LOW_END 500.0f
#define MID_END 2000.0f
#define MAX_FREQ 7500.0f

// exact FFT-bin boundaries for 16 kHz / 512-point FFT
// bin spacing = 16000 / 512 = 31.25 Hz
#define FIRST_BIN 4
#define LOW_END_BIN 16
#define MID_END_BIN 64
#define LAST_BIN 240

// mfcc
#define MEL_FILTERS 20
#define MFCC_COUNT 5

// features
#define FRAME_FEATURES 10
#define FINAL_FEATURES 20

// constants
#define PI 3.14159265358979323846f
#define EPSILON 1e-12f

// approximately 125 Hz first-order HPF at 16 kHz
#define HPF_ALPHA 0.953f

// Q15 constants
#define Q15_SCALE 32767.0f
#define Q15_HEADROOM 30000.0f

/*
RP2040 ADC: 48 MHz ADC clock

adc_set_clkdiv() sets the average conversion-start period to:
1 + divider ADC-clock cycles

48,000,000 / 16,000 = 3000 cycles per sample

divider = 3000 - 1 = 2999
*/
#define ADC_CLOCK_HZ 48000000.0f
#define ADC_CLKDIV ((ADC_CLOCK_HZ / SAMPLE_RATE) - 1.0f)

// AUDIO / DSP BUFFERS
// two raw ADC buffers are used for ping-pong capture
// the CPU processes one completed buffer, DMA captures the next 500 ms window into the other buffer
static uint16_t raw_audio[2][AUDIO_SAMPLES];

static int32_t filtered_audio[AUDIO_SAMPLES]; // Q4 ADC counts

// one fixed-point FFT workspace per RP2040 core
typedef struct {
    int16_t real[FFT_SIZE];
    int16_t imag[FFT_SIZE];
    uint32_t power_spectrum[FFT_BINS];
} dsp_workspace_t;

static dsp_workspace_t workspace_core0;

// stores each frame's 10 features
// after both cores finish, Core 0 aggregates them in the original frame order
// so the final 20-feature vector format stays the same
static int32_t all_frame_features[NUM_FRAMES][FRAME_FEATURES]; // all Q8

static int mel_bins[MEL_FILTERS + 2];

// precomputed Hamming window values
// calculated once during startup instead of using cosf() for every frame
static int16_t hamming_table[FRAME_SIZE]; // Q15

// precomputed Q15 FFT twiddle factors
// calculated once during startup instead of using cosf()/sinf() inside every FFT
static int16_t fft_cos_q15[FFT_SIZE / 2];
static int16_t fft_sin_q15[FFT_SIZE / 2];

// precomputed DCT cosine values used by MFCC
// calculated once during startup instead of using cosf() for every MFCC coefficient
static int16_t dct_table[MFCC_COUNT][MEL_FILTERS]; // Q14

// precomputed Mel-filter weights
// removes repeated divisions from every MFCC calculation
static int16_t mel_weight_table[MEL_FILTERS][FFT_BINS]; // Q15

// precomputed frequency value for each FFT bin
// removes repeated frequency calculations from every frame
static uint16_t frequency_table[FFT_BINS]; // Hz

// feature order
enum {
    FEAT_RMS = 0,
    FEAT_CENTROID,
    FEAT_LOW_RATIO,
    FEAT_MID_RATIO,
    FEAT_HIGH_RATIO,
    FEAT_MFCC1,
    FEAT_MFCC2,
    FEAT_MFCC3,
    FEAT_MFCC4,
    FEAT_MFCC5
};

// FIXED-POINT FFT
static unsigned int reverse_bits(unsigned int x, int bits)
{
    unsigned int result = 0;

    for (int i = 0; i < bits; i++) {
        result <<= 1;
        result |= (x & 1);
        x >>= 1;
    }

    return result;
}

// Q15 multiply: (a * b) / 32768
static inline int32_t q15_mul(int16_t a, int16_t b)
{
    return ((int32_t)a * (int32_t)b) >> 15;
}

// fixed-point radix-2 FFT
//
// each butterfly is scaled by 1 bit per stage.
// this prevents Q15 overflow.
// the resulting overall FFT scale does not affect:
// - spectral centroid
// - normalised band-energy ratios
// - MFCC coefficients 1..5
// in exact arithmetic. Finite Q15 precision, flooring, and per-frame
// scaling CAN change MFCC values relative to the original float FFT.
// This requires side-by-side validation before reusing an existing model.
static void fft_q15(int16_t *real, int16_t *imag, int N)
{
    int bits = 0;

    for (int n = N; n > 1; n >>= 1) {
        bits++;
    }

    /* bit reversal */
    for (int i = 0; i < N; i++) {
        int j = reverse_bits(i, bits);

        if (j > i) {
            int16_t tmp_real = real[i];
            int16_t tmp_imag = imag[i];

            real[i] = real[j];
            imag[i] = imag[j];

            real[j] = tmp_real;
            imag[j] = tmp_imag;
        }
    }

    // radix-2 FFT
    for (int size = 2; size <= N; size <<= 1) {
        int half = size / 2;

        for (int start = 0; start < N; start += size) {
            for (int j = 0; j < half; j++) {
                int twiddle_index = j * (FFT_SIZE / size);

                int16_t wr = fft_cos_q15[twiddle_index];
                int16_t wi = fft_sin_q15[twiddle_index];

                int16_t odd_real = real[start + j + half];
                int16_t odd_imag = imag[start + j + half];

                int32_t tr =
                    q15_mul(wr, odd_real) -
                    q15_mul(wi, odd_imag);

                int32_t ti =
                    q15_mul(wr, odd_imag) +
                    q15_mul(wi, odd_real);

                int32_t even_real = real[start + j];
                int32_t even_imag = imag[start + j];

                // divide every butterfly output by 2
                // to maintain Q15 headroom through all FFT stages
                real[start + j] =
                    (int16_t)((even_real + tr) >> 1);

                imag[start + j] =
                    (int16_t)((even_imag + ti) >> 1);

                real[start + j + half] =
                    (int16_t)((even_real - tr) >> 1);

                imag[start + j + half] =
                    (int16_t)((even_imag - ti) >> 1);
            }
        }
    }
}

// hamming window
// initialise Hamming window lookup table once at startup
static void init_hamming_table(void)
{
    for (int n = 0; n < FRAME_SIZE; n++) {
        hamming_table[n] = (int16_t)lrintf(32767.0f *
            (0.54f - 0.46f * cosf((2.0f * PI * n) / (FRAME_SIZE - 1))));
    }
}

// initialise Q15 FFT sine/cosine lookup tables once at startup
static void init_fft_tables(void)
{
    for (int i = 0; i < FFT_SIZE / 2; i++) {
        float angle = (-2.0f * PI * i) / FFT_SIZE;

        int32_t cq = (int32_t)lrintf(cosf(angle) * Q15_SCALE);
        int32_t sq = (int32_t)lrintf(sinf(angle) * Q15_SCALE);

        if (cq > 32767) cq = 32767;
        if (cq < -32768) cq = -32768;
        if (sq > 32767) sq = 32767;
        if (sq < -32768) sq = -32768;

        fft_cos_q15[i] = (int16_t)cq;
        fft_sin_q15[i] = (int16_t)sq;
    }
}

// initialise MFCC DCT cosine lookup table once at startup
static void init_dct_table(void)
{
    for (int c = 0; c < MFCC_COUNT; c++) {
        int coefficient = c + 1;

        for (int m = 0; m < MEL_FILTERS; m++) {
            dct_table[c][m] = (int16_t)lrintf(16384.0f *
                cosf((PI * coefficient * (m + 0.5f)) / MEL_FILTERS));
        }
    }
}

// initialise FFT-bin frequency lookup table once at startup
static void init_frequency_table(void)
{
    for (int bin = 0; bin < FFT_BINS; bin++) {
        frequency_table[bin] =
            (uint16_t)((bin * SAMPLE_RATE) / FFT_SIZE);
    }
}

// mel conversion
static float hz_to_mel(float hz)
{
    return 2595.0f * log10f(1.0f + (hz / 700.0f));
}

static float mel_to_hz(float mel)
{
    return 700.0f * (powf(10.0f, mel / 2595.0f) - 1.0f);
}

// mel filterbank initialisation
static void init_mel_filterbank(void)
{
    float min_mel = hz_to_mel(MIN_FREQ);
    float max_mel = hz_to_mel(MAX_FREQ);

    for (int i = 0; i < MEL_FILTERS + 2; i++) {
        float mel =
            min_mel +
            ((max_mel - min_mel) * i / (MEL_FILTERS + 1));

        float hz = mel_to_hz(mel);

        int bin =
            (int)floorf(((FFT_SIZE + 1) * hz) / SAMPLE_RATE);

        if (bin < 0) {
            bin = 0;
        }

        if (bin > FFT_SIZE / 2) {
            bin = FFT_SIZE / 2;
        }

        mel_bins[i] = bin;
    }
}

// precompute all Mel-filter weights once at startup
// this keeps the same triangular Mel filters but removes repeated division operations
static void init_mel_weight_table(void)
{
    for (int m = 0; m < MEL_FILTERS; m++) {
        for (int k = 0; k < FFT_BINS; k++) {
            mel_weight_table[m][k] = 0;
        }

        int left = mel_bins[m];
        int centre = mel_bins[m + 1];
        int right = mel_bins[m + 2];

        // rising triangle
        if (centre > left) {
            for (int k = left; k < centre; k++) {
                mel_weight_table[m][k] =
                    (int16_t)((32767L * (k - left)) /
                              (centre - left));
            }
        }

        // falling triangle
        if (right > centre) {
            for (int k = centre; k < right; k++) {
                mel_weight_table[m][k] =
                    (int16_t)((32767L * (right - k)) /
                              (right - centre));
            }
        }
    }
}

/*
   preprocessing
   1. estimate DC microphone bias
   2. remove DC
   3. high-pass filter

   Integer representation:
   ADC samples: unsigned 12-bit
   Centered/filtered samples: signed Q4 ADC counts
   HPF alpha: Q15, accumulators: int64_t
*/
#define HPF_ALPHA_Q15 31228  // round(0.953 * 32768)
#define FEATURE_Q 8           // 20 final features use Q8 (value * 256)
#define LOG2_TO_LN_Q12 2839   // round(ln(2) * 4096)

static uint32_t isqrt64(uint64_t n)
{
    // Restoring integer square root (no floating point).
    uint64_t bit = (uint64_t)1 << 62, result = 0;
    while (bit > n) bit >>= 2;
    while (bit) {
        if (n >= result + bit) {
            n -= result + bit;
            result = (result >> 1) + bit;
        } else {
            result >>= 1;
        }
        bit >>= 2;
    }
    return (uint32_t)result;
}

static int32_t log_q12(uint64_t x)
{
    // Natural logarithm approximation in Q12 using normalized base-2
    // mantissa and quadratic log2(1+u) approximation.
    // Non-positive energies use a fixed floor.
    if (!x) return -24 * 4096;
    int shift = 0;
    uint64_t y = x;
    while (y >= 2) { y >>= 1; shift++; }
    uint32_t mant = (uint32_t)((x << 15) >> shift);
    int32_t u = (int32_t)mant - 32768;  // Q15 [0,1)
    // ln(1+u) ~ u - u²/2 + u³/3 - u⁴/4, Q15
    int64_t u2 = ((int64_t)u*u)>>15;
    int64_t u3 = (u2*u)>>15;
    int64_t u4 = (u3*u)>>15;
    int32_t ln_mant_q15 = (int32_t)(u-u2/2+u3/3-u4/4);
    return shift * LOG2_TO_LN_Q12 + (ln_mant_q15 >> 3);
}

static void preprocess_audio(const uint16_t *input)
{
    int64_t sum = 0;
    for (int i = 0; i < AUDIO_SAMPLES; i++) sum += input[i];
    int32_t mean_q4 = (int32_t)((sum << 4) / AUDIO_SAMPLES);
    int32_t previous_input = 0;
    int32_t previous_output = 0;

    for (int i = 0; i < AUDIO_SAMPLES; i++) {
        int32_t centered = ((int32_t)input[i] << 4) - mean_q4;
        int64_t accum = (int64_t)previous_output + centered - previous_input;
        int32_t filtered = (int32_t)((accum * HPF_ALPHA_Q15) >> 15);
        previous_input = centered;
        previous_output = filtered;
        filtered_audio[i] = filtered;
    }
}

// FIXED-POINT FFT + POWER SPECTRUM
static void calculate_spectrum(const int32_t *frame, dsp_workspace_t *w)
{
    int32_t max_abs = 1;
    for (int i=0;i<FRAME_SIZE;i++) {
        int32_t v = frame[i] < 0 ? -frame[i] : frame[i];
        if (v > max_abs) max_abs = v;
    }
    // Frame normalization uses integer division, matching previous
    // Q15 headroom strategy; actual values differ from float FFT.
    int64_t gain_q16 = ((int64_t)30000 << 16) / max_abs;
    for (int i=0;i<FRAME_SIZE;i++) {
        int64_t scaled = ((int64_t)frame[i] * hamming_table[i]) >> 15;
        int64_t q = (scaled * gain_q16) >> 16;
        if (q > 32767) q = 32767;
        if (q < -32768) q = -32768;
        w->real[i] = (int16_t)q;
        w->imag[i] = 0;
    }
    for (int i=FRAME_SIZE;i<FFT_SIZE;i++) {
        w->real[i] = 0;
        w->imag[i] = 0;
    }
    fft_q15(w->real, w->imag, FFT_SIZE);
    for (int i=0;i<FFT_BINS;i++) {
        int32_t re = w->real[i], im = w->imag[i];
        w->power_spectrum[i] = (uint32_t)(re*re + im*im);
    }
}

// MFCC extraction: log energies in Q12, DCT coeffs in Q14;
// output is Q8 after multiplying by scale of 256.
static void calculate_mfcc(const uint32_t *powers, int32_t mfcc[MFCC_COUNT])
{
    int32_t mel_log[MEL_FILTERS];
    for (int m=0;m<MEL_FILTERS;m++) {
        uint64_t energy_q15 = 0;
        for (int k=mel_bins[m]; k<mel_bins[m+2]; k++)
            energy_q15 += (uint64_t)powers[k] * (uint16_t)mel_weight_table[m][k];
        uint64_t energy = energy_q15 >> 15;
        mel_log[m] = log_q12(energy);
    }
    for (int c=0;c<MFCC_COUNT;c++) {
        int64_t dct = 0;
        for (int m=0;m<MEL_FILTERS;m++)
            dct += (int64_t)mel_log[m] * dct_table[c][m];
        mfcc[c] = (int32_t)(dct >> 18); // Q12*Q14 -> Q8
    }
}

// extract 10 features from ONE 25 ms frame, each in Q8
static void extract_frame_features(
    const int32_t *frame, int32_t features[FRAME_FEATURES], dsp_workspace_t *w)
{
    uint64_t sum_sq = 0;
    for (int i=0;i<FRAME_SIZE;i++)
        sum_sq += (int64_t)frame[i] * frame[i];
    // Frame is Q4; convert RMS to Q8.
    uint32_t rms_q4 = isqrt64(sum_sq / FRAME_SIZE);
    features[FEAT_RMS] = (int32_t)rms_q4 << 4;
    calculate_spectrum(frame,w);

    uint64_t mag_sum = 0, weighted_sum = 0;
    uint64_t low=0,mid=0,high=0;
    for (int bin=FIRST_BIN;bin<=LAST_BIN;bin++) {
        uint32_t p = w->power_spectrum[bin];
        uint32_t mag = isqrt64(p);
        mag_sum += mag;
        weighted_sum += (uint64_t)frequency_table[bin] * mag;
        if (bin<LOW_END_BIN) low+=p;
        else if (bin<MID_END_BIN) mid+=p;
        else high+=p;
    }
    uint64_t total=low+mid+high;
    features[FEAT_CENTROID] = mag_sum ?
        (int32_t)((weighted_sum << FEATURE_Q) / mag_sum) : 0;
    features[FEAT_LOW_RATIO] = total ?
        (int32_t)((low << FEATURE_Q)/total):0;
    features[FEAT_MID_RATIO] = total ?
        (int32_t)((mid << FEATURE_Q)/total):0;
    features[FEAT_HIGH_RATIO] = total ?
        (int32_t)((high << FEATURE_Q)/total):0;

    int32_t mfcc[MFCC_COUNT];
    calculate_mfcc(w->power_spectrum,mfcc);
    for (int c=0;c<MFCC_COUNT;c++)
        features[FEAT_MFCC1+c] = mfcc[c];
}


static void build_feature_vector(
    int32_t output[FINAL_FEATURES]
)
{
    for (int frame=0; frame<NUM_FRAMES; frame++) {
        extract_frame_features(&filtered_audio[frame * HOP_SIZE],
                               all_frame_features[frame], &workspace_core0);
    }

    int64_t sum[FRAME_FEATURES] = {0};
    uint64_t sum_squared[FRAME_FEATURES] = {0};

    // keep aggregation in original frame order
    for (int frame = 0; frame < NUM_FRAMES; frame++) {
        for (int f = 0; f < FRAME_FEATURES; f++) {
            int32_t value = all_frame_features[frame][f];
            sum[f] += value;
            sum_squared[f] += (uint64_t)((int64_t)value * value);
        }
    }

    for (int f = 0; f < FRAME_FEATURES; f++) {
        int32_t mean = (int32_t)(sum[f] / NUM_FRAMES);
        int64_t variance = (int64_t)(sum_squared[f] / NUM_FRAMES)
                           - (int64_t)mean * mean;
        if (variance < 0) variance = 0;
        output[f] = mean;
        output[FRAME_FEATURES + f] = (int32_t)isqrt64((uint64_t)variance);
    }
}


void audio_dsp_init(void)
{
    init_mel_filterbank();
    init_hamming_table();
    init_fft_tables();
    init_dct_table();
    init_frequency_table();
    init_mel_weight_table();
}

void audio_dsp_process(const uint16_t samples[AUDIO_DSP_WINDOW_SAMPLES],
                       int32_t out_q8[AUDIO_DSP_FEATURE_COUNT])
{
    if (!samples || !out_q8) return;
    preprocess_audio(samples);
    build_feature_vector(out_q8);
}
