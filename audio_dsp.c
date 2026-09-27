#include <stdio.h>
#include <stdint.h>
#include <math.h>

#include "pico/stdlib.h"
#include "hardware/adc.h"

/* 
Wiring:
AUD -> GP26 / ADC0
GND -> GND
VCC -> 3V3
*/

// PIN
#define MIC_PIN 26
#define MIC_ADC_INPUT 0


// audio configuration
#define SAMPLE_RATE 16000

// 500 ms classification window
#define AUDIO_SAMPLES 8000

// 25 ms frame at 16 kHz
#define FRAME_SIZE 400

// 10 ms hop at 16 kHz
#define HOP_SIZE 160

// no of 25 ms frames inside 500 ms
#define NUM_FRAMES 48

#define FFT_SIZE 512


// frequency band

#define MIN_FREQ 125.0f
#define LOW_END 500.0f
#define MID_END 2000.0f
#define MAX_FREQ 7500.0f


// mfcc

#define MEL_FILTERS 20
#define MFCC_COUNT  5


// features

#define FRAME_FEATURES 10
#define FINAL_FEATURES 20


// constants

#define PI 3.14159265358979323846f
#define EPSILON 1e-12f

// approximately 125 Hz first-order HPF at 16 kHz
#define HPF_ALPHA 0.953f


typedef struct {
    float real;
    float imag;
} complex_t;


// buffers

static uint16_t raw_audio[AUDIO_SAMPLES];
static float filtered_audio[AUDIO_SAMPLES];

static complex_t fft_buffer[FFT_SIZE];

static float power_spectrum[(FFT_SIZE / 2) + 1];

static int mel_bins[MEL_FILTERS + 2];


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


// FFT

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


static void fft(complex_t *buffer, int N)
{
    int bits = 0;

    for (int n = N; n > 1; n >>= 1)
        bits++;


    /* bit reversal */
    for (int i = 0; i < N; i++) {

        int j = reverse_bits(i, bits);

        if (j > i) {
            complex_t tmp = buffer[i];
            buffer[i] = buffer[j];
            buffer[j] = tmp;
        }
    }


    // radix-2 FFT
    for (int size = 2; size <= N; size <<= 1) {

        int half = size / 2;

        float angle_step =
            -2.0f * PI / (float)size;


        for (int start = 0; start < N; start += size) {

            for (int j = 0; j < half; j++) {

                float angle =
                    angle_step * j;

                float wr = cosf(angle);
                float wi = sinf(angle);

                complex_t even =
                    buffer[start + j];

                complex_t odd =
                    buffer[start + j + half];

                float tr =
                    wr * odd.real -
                    wi * odd.imag;

                float ti =
                    wr * odd.imag +
                    wi * odd.real;


                buffer[start + j].real =
                    even.real + tr;

                buffer[start + j].imag =
                    even.imag + ti;

                buffer[start + j + half].real =
                    even.real - tr;

                buffer[start + j + half].imag =
                    even.imag - ti;
            }
        }
    }
}


// hamming window

static float hamming(int n)
{
    return 0.54f -
           0.46f *
           cosf(
               2.0f * PI * n /
               (FRAME_SIZE - 1)
           );
}


// mel conversion

static float hz_to_mel(float hz)
{
    return 2595.0f *
           log10f(
               1.0f +
               hz / 700.0f
           );
}


static float mel_to_hz(float mel)
{
    return 700.0f *
           (
               powf(
                   10.0f,
                   mel / 2595.0f
               )
               - 1.0f
           );
}


// mel filterbank initialisation

static void init_mel_filterbank(void)
{
    float min_mel =
        hz_to_mel(MIN_FREQ);

    float max_mel =
        hz_to_mel(MAX_FREQ);


    for (int i = 0;
         i < MEL_FILTERS + 2;
         i++) {

        float mel =
            min_mel +
            (
                (max_mel - min_mel) *
                i /
                (MEL_FILTERS + 1)
            );

        float hz =
            mel_to_hz(mel);

        int bin =
            (int)floorf(
                (FFT_SIZE + 1) *
                hz /
                SAMPLE_RATE
            );

        if (bin < 0)
            bin = 0;

        if (bin > FFT_SIZE / 2)
            bin = FFT_SIZE / 2;

        mel_bins[i] = bin;
    }
}


// capture 500 ms of audio at 16 kHz

static void capture_audio(void)
{
    absolute_time_t start =
        get_absolute_time();


    for (int i = 0;
         i < AUDIO_SAMPLES;
         i++) {

        /*
        target sample time
        16 kHz = one sample every 62.5 us
        integer maths distributes fractional timing
         */

        uint64_t target_us =
            ((uint64_t)i * 1000000ULL)
            / SAMPLE_RATE;


        busy_wait_until(
            delayed_by_us(
                start,
                target_us
            )
        );


        raw_audio[i] =
            adc_read();
    }
}


/*
   preprocessing
   1. estimate DC microphone bias
   2. remove DC
   3. high-pass filter
*/

static void preprocess_audio(void)
{
    float mean = 0.0f;


    for (int i = 0;
         i < AUDIO_SAMPLES;
         i++) {

        mean +=
            (float)raw_audio[i];
    }


    mean /= AUDIO_SAMPLES;


    float previous_input = 0.0f;
    float previous_output = 0.0f;


    for (int i = 0;
         i < AUDIO_SAMPLES;
         i++) {

        float centered =
            (float)raw_audio[i] -
            mean;


        float filtered =
            HPF_ALPHA *
            (
                previous_output +
                centered -
                previous_input
            );


        previous_input =
            centered;

        previous_output =
            filtered;


        filtered_audio[i] =
            filtered;
    }
}


// FFT + power spectrum

static void calculate_spectrum(
    const float *frame
)
{
    // apply Hamming window 

    for (int i = 0;
         i < FRAME_SIZE;
         i++) {

        fft_buffer[i].real =
            frame[i] *
            hamming(i);

        fft_buffer[i].imag =
            0.0f;
    }


    // zero padding 400 -> 512

    for (int i = FRAME_SIZE;
         i < FFT_SIZE;
         i++) {

        fft_buffer[i].real = 0.0f;
        fft_buffer[i].imag = 0.0f;
    }


    fft(
        fft_buffer,
        FFT_SIZE
    );


    // calculate power

    for (int i = 0;
         i <= FFT_SIZE / 2;
         i++) {

        float re =
            fft_buffer[i].real;

        float im =
            fft_buffer[i].imag;


        power_spectrum[i] =
            re * re +
            im * im;
    }
}


// MFCC extraction

static void calculate_mfcc(
    float mfcc[MFCC_COUNT]
)
{
    float mel_energy[MEL_FILTERS];


    // mel filter bank

    for (int m = 0;
         m < MEL_FILTERS;
         m++) {

        int left =
            mel_bins[m];

        int centre =
            mel_bins[m + 1];

        int right =
            mel_bins[m + 2];


        float energy = 0.0f;


        // rising triangle

        if (centre > left) {

            for (int k = left;
                 k < centre;
                 k++) {

                float weight =
                    (float)(k - left) /
                    (float)(centre - left);


                energy +=
                    power_spectrum[k] *
                    weight;
            }
        }


        // falling triangle

        if (right > centre) {

            for (int k = centre;
                 k < right;
                 k++) {

                float weight =
                    (float)(right - k) /
                    (float)(right - centre);


                energy +=
                    power_spectrum[k] *
                    weight;
            }
        }


        mel_energy[m] =
            logf(
                energy +
                EPSILON
            );
    }


    /*
     * DCT
     * skip coefficient 0 because RMS already provides overall signal energy
     */

    for (int c = 0;
         c < MFCC_COUNT;
         c++) {

        int coefficient =
            c + 1;

        float result = 0.0f;


        for (int m = 0;
             m < MEL_FILTERS;
             m++) {

            result +=
                mel_energy[m] *
                cosf(
                    PI *
                    coefficient *
                    (m + 0.5f) /
                    MEL_FILTERS
                );
        }


        mfcc[c] =
            result;
    }
}


// extract 10 features from ONE 25 ms frame

static void extract_frame_features(
    const float *frame,
    float features[FRAME_FEATURES]
)
{
    // RMS

    float sum_sq = 0.0f;


    for (int i = 0;
         i < FRAME_SIZE;
         i++) {

        sum_sq +=
            frame[i] *
            frame[i];
    }


    float rms =
        sqrtf(
            sum_sq /
            FRAME_SIZE
        );


    // FFT

    calculate_spectrum(
        frame
    );


    // spectral features

    float weighted_sum = 0.0f;
    float magnitude_sum = 0.0f;

    float low_energy = 0.0f;
    float mid_energy = 0.0f;
    float high_energy = 0.0f;


    int first_bin =
        (int)ceilf(
            MIN_FREQ *
            FFT_SIZE /
            SAMPLE_RATE
        );


    int last_bin =
        (int)floorf(
            MAX_FREQ *
            FFT_SIZE /
            SAMPLE_RATE
        );


    for (int bin = first_bin;
         bin <= last_bin;
         bin++) {

        float frequency =
            (float)bin *
            SAMPLE_RATE /
            FFT_SIZE;


        float power =
            power_spectrum[bin];


        float magnitude =
            sqrtf(power);


        // spectral centroid

        weighted_sum +=
            frequency *
            magnitude;

        magnitude_sum +=
            magnitude;


        // frequency bands

        if (frequency < LOW_END) {

            low_energy +=
                power;
        }

        else if (frequency < MID_END) {

            mid_energy +=
                power;
        }

        else {

            high_energy +=
                power;
        }
    }


    float centroid = 0.0f;


    if (magnitude_sum > EPSILON) {

        centroid =
            weighted_sum /
            magnitude_sum;
    }


    // normalised band energy

    float total_energy =
        low_energy +
        mid_energy +
        high_energy +
        EPSILON;


    float low_ratio =
        low_energy /
        total_energy;


    float mid_ratio =
        mid_energy /
        total_energy;


    float high_ratio =
        high_energy /
        total_energy;


    // MFCC

    float mfcc[MFCC_COUNT];

    calculate_mfcc(
        mfcc
    );


    // feature vector

    features[FEAT_RMS] =
        rms;

    features[FEAT_CENTROID] =
        centroid;

    features[FEAT_LOW_RATIO] =
        low_ratio;

    features[FEAT_MID_RATIO] =
        mid_ratio;

    features[FEAT_HIGH_RATIO] =
        high_ratio;


    for (int i = 0;
         i < MFCC_COUNT;
         i++) {

        features[FEAT_MFCC1 + i] =
            mfcc[i];
    }
}


/*
   Aggregate 48 frames into final 20-value vector
   [0..9]   = feature means
   [10..19] = feature standard deviations
*/

static void build_feature_vector(
    float output[FINAL_FEATURES]
)
{
    float sum[FRAME_FEATURES] = {0};
    float sum_squared[FRAME_FEATURES] = {0};


    for (int frame = 0;
         frame < NUM_FRAMES;
         frame++) {

        int offset =
            frame *
            HOP_SIZE;


        float frame_features[
            FRAME_FEATURES
        ];


        extract_frame_features(
            &filtered_audio[offset],
            frame_features
        );


        for (int f = 0;
             f < FRAME_FEATURES;
             f++) {

            sum[f] +=
                frame_features[f];

            sum_squared[f] +=
                frame_features[f] *
                frame_features[f];
        }
    }


    for (int f = 0;
         f < FRAME_FEATURES;
         f++) {

        float mean =
            sum[f] /
            NUM_FRAMES;


        float variance =
            sum_squared[f] /
            NUM_FRAMES -
            mean * mean;


        if (variance < 0.0f)
            variance = 0.0f;


        output[f] =
            mean;


        output[
            FRAME_FEATURES + f
        ] =
            sqrtf(variance);
    }
}


// print final ML feature vector


static void print_feature_vector(
    const float vector[FINAL_FEATURES]
)
{
    printf("FEATURE_VECTOR=[");


    for (int i = 0;
         i < FINAL_FEATURES;
         i++) {

        printf(
            "%.6f",
            vector[i]
        );


        if (i != FINAL_FEATURES - 1)
            printf(",");
    }


    printf("]\n");
}


// main

int main(void)
{
    stdio_init_all();


    adc_init();

    adc_gpio_init(
        MIC_PIN
    );

    adc_select_input(
        MIC_ADC_INPUT
    );


    init_mel_filterbank();


    sleep_ms(2000);


    printf("\nMOSAIC Member 1 DSP\n");

    printf("Sampling rate : 16 kHz\n");
    printf("Window        : 500 ms\n");
    printf("Frame         : 25 ms\n");
    printf("Hop           : 10 ms\n");
    printf("FFT           : 512\n");
    printf("Frequency     : 125 - 7500 Hz\n");
    printf("MFCC          : 5\n");
    printf("Features      : 20\n\n");


    while (true) {

        float feature_vector[
            FINAL_FEATURES
        ];


        // acquire microphone signal

        capture_audio();


        // filter / preprocess

        preprocess_audio();


        // extract DSP features

        build_feature_vector(
            feature_vector
        );


        // send features for ML

        print_feature_vector(
            feature_vector
        );
    }
}