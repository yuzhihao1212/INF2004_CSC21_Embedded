#include <stdio.h>
#include <stdint.h>
#include <math.h>

#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/structs/adc.h"

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

/*
RP2040 ADC: 48 MHz ADC clock

adc_set_clkdiv() sets the average conversion-start period to:
1 + divider ADC-clock cycles

48,000,000 / 16,000 = 3000 cycles per sample

divider = 3000 - 1 = 2999
*/
#define ADC_CLOCK_HZ 48000000.0f
#define ADC_CLKDIV ((ADC_CLOCK_HZ / SAMPLE_RATE) - 1.0f)

// collect background sound sample
#define DATASET_LABEL "background"
// #define DATASET_LABEL "lecture"
// #define DATASET_LABEL "conversation"
// #define DATASET_LABEL "transient"

static uint32_t sample_id = 0;

typedef struct {
    float real;
    float imag;
} complex_t;

typedef struct {
    complex_t fft_buffer[FFT_SIZE];
    float power_spectrum[FFT_BINS];
} dsp_workspace_t;


// AUDIO / DSP BUFFERS
// two raw ADC buffers are used for ping-pong capture
// the CPU processes one completed buffer, DMA captures the next 500 ms window into the other buffer
static uint16_t raw_audio[2][AUDIO_SAMPLES];

static float filtered_audio[AUDIO_SAMPLES];

// one FFT/power workspace per RP2040 core so both cores can process frames at the same time
static dsp_workspace_t workspace_core0;
static dsp_workspace_t workspace_core1;

// stores each frame's 10 features
// after both cores finish, Core 0 aggregates them in the original frame order
// so the final 20-feature vector format stays the same
static float all_frame_features[NUM_FRAMES][FRAME_FEATURES];

static int mel_bins[MEL_FILTERS + 2];

// precomputed Hamming window values
// calculated once during startup instead of using cosf() for every frame
static float hamming_table[FRAME_SIZE];

// precomputed FFT twiddle factors
// calculated once during startup instead of using cosf()/sinf() inside every FFT
static float fft_cos[FFT_SIZE / 2];
static float fft_sin[FFT_SIZE / 2];

// precomputed DCT cosine values used by MFCC
// calculated once during startup instead of using cosf() for every MFCC coefficient
static float dct_table[MFCC_COUNT][MEL_FILTERS];

// precomputed Mel-filter weights
// removes repeated divisions from every MFCC calculation
static float mel_weight_table[MEL_FILTERS][FFT_BINS];

// precomputed frequency value for each FFT bin
// removes repeated frequency calculations from every frame
static float frequency_table[FFT_BINS];

// DMA STATE
static uint dma_chan;
static dma_channel_config dma_cfg;

// set by the DMA interrupt when one complete 500 ms window is captured
static volatile bool capture_done = false;

// MULTICORE STATE
#define CORE1_WORK_COMMAND 0xA501u
#define CORE1_DONE_COMMAND 0xA502u

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


// DMA / ADC CAPTURE
// DMA completion interrupt
// when exactly AUDIO_SAMPLES samples have been transferred:
// 1. stop the ADC,
// 2. drain any remaining FIFO data
// 3. mark the buffer as complete
// prevent overflowing
static void dma_handler(void)
{
    uint32_t mask = 1u << dma_chan;

    if (dma_hw->ints0 & mask) {
        // acknowledge DMA IRQ
        dma_hw->ints0 = mask;

        // stop free-running ADC immediately after the 8000th sample
        adc_run(false);

        // discard anything left in the FIFO
        adc_fifo_drain();

        capture_done = true;
    }
}

// configure ADC FIFO + DMA for fixed-rate 16 kHz capture
static void init_dma_audio_capture(void)
{
    adc_init();
    adc_gpio_init(MIC_PIN);
    adc_select_input(MIC_ADC_INPUT);

    /*
    ADC FIFO:
    - enable FIFO
    - enable DMA request
    - request DMA when >= 1 sample is available
    - do not store error flag
    - do not byte-shift; keep full 12-bit samples in uint16_t
    */
    adc_fifo_setup(
        true,
        true,
        1,
        false,
        false
    );

    // fixed 16 kHz ADC conversion-start rate
    adc_set_clkdiv(ADC_CLKDIV);

    dma_chan = dma_claim_unused_channel(true);

    dma_cfg = dma_channel_get_default_config(dma_chan);

    // ADC FIFO: 16-bit read; destination buffer increments
    channel_config_set_transfer_data_size(
        &dma_cfg,
        DMA_SIZE_16
    );

    channel_config_set_read_increment(
        &dma_cfg,
        false
    );

    channel_config_set_write_increment(
        &dma_cfg,
        true
    );

    // pace DMA transfers using ADC FIFO requests
    channel_config_set_dreq(
        &dma_cfg,
        DREQ_ADC
    );

    // use DMA IRQ 0 to know when 8000 samples have been captured
    dma_channel_set_irq0_enabled(
        dma_chan,
        true
    );

    irq_set_exclusive_handler(
        DMA_IRQ_0,
        dma_handler
    );

    irq_set_enabled(
        DMA_IRQ_0,
        true
    );
}

// start filling one of the two raw ADC buffers
// waits for ADC FIFO data, safe to configure/start the DMA before starting ADC conversion
static void start_dma_capture(uint16_t *destination)
{
    capture_done = false;

    // ensure a clean start for each 500 ms window
    adc_run(false);
    adc_fifo_drain();

    dma_channel_configure(
        dma_chan,
        &dma_cfg,
        destination,
        &adc_hw->fifo,
        AUDIO_SAMPLES,
        true
    );

    adc_run(true);
}

// wait until DMA has captured one complete 500 ms audio window
static void wait_for_capture(void)
{
    while (!capture_done) {
        tight_loop_contents();
    }
}


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

    for (int n = N; n > 1; n >>= 1) {
        bits++;
    }

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

        // FFT twiddle factors are precomputed once during startup
        for (int start = 0; start < N; start += size) {
            for (int j = 0; j < half; j++) {
                // lookup precomputed twiddle factor
                // FFT_SIZE / size maps this FFT stage into the full lookup table
                int twiddle_index = j * (FFT_SIZE / size);

                float wr = fft_cos[twiddle_index];
                float wi = fft_sin[twiddle_index];

                complex_t even = buffer[start + j];
                complex_t odd = buffer[start + j + half];

                float tr = (wr * odd.real) - (wi * odd.imag);
                float ti = (wr * odd.imag) + (wi * odd.real);

                buffer[start + j].real = even.real + tr;
                buffer[start + j].imag = even.imag + ti;

                buffer[start + j + half].real = even.real - tr;
                buffer[start + j + half].imag = even.imag - ti;
            }
        }
    }
}


// hamming window
// initialise Hamming window lookup table once at startup
static void init_hamming_table(void)
{
    for (int n = 0; n < FRAME_SIZE; n++) {
        hamming_table[n] =
            0.54f -
            0.46f * cosf((2.0f * PI * n) / (FRAME_SIZE - 1));
    }
}

// initialise FFT sine/cosine lookup tables once at startup
static void init_fft_tables(void)
{
    for (int i = 0; i < FFT_SIZE / 2; i++) {
        float angle = (-2.0f * PI * i) / FFT_SIZE;

        fft_cos[i] = cosf(angle);
        fft_sin[i] = sinf(angle);
    }
}

// initialise MFCC DCT cosine lookup table once at startup
static void init_dct_table(void)
{
    for (int c = 0; c < MFCC_COUNT; c++) {
        int coefficient = c + 1;

        for (int m = 0; m < MEL_FILTERS; m++) {
            dct_table[c][m] =
                cosf((PI * coefficient * (m + 0.5f)) / MEL_FILTERS);
        }
    }
}

// initialise FFT-bin frequency lookup table once at startup
static void init_frequency_table(void)
{
    for (int bin = 0; bin < FFT_BINS; bin++) {
        frequency_table[bin] =
            ((float)bin * SAMPLE_RATE) / FFT_SIZE;
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
            mel_weight_table[m][k] = 0.0f;
        }

        int left = mel_bins[m];
        int centre = mel_bins[m + 1];
        int right = mel_bins[m + 2];

        // rising triangle
        if (centre > left) {
            for (int k = left; k < centre; k++) {
                mel_weight_table[m][k] =
                    (float)(k - left) / (float)(centre - left);
            }
        }

        // falling triangle
        if (right > centre) {
            for (int k = centre; k < right; k++) {
                mel_weight_table[m][k] =
                    (float)(right - k) / (float)(right - centre);
            }
        }
    }
}


/*
   preprocessing
   1. estimate DC microphone bias
   2. remove DC
   3. high-pass filter
*/
static void preprocess_audio(const uint16_t *input)
{
    float mean = 0.0f;

    for (int i = 0; i < AUDIO_SAMPLES; i++) {
        mean += (float)input[i];
    }

    mean /= AUDIO_SAMPLES;

    float previous_input = 0.0f;
    float previous_output = 0.0f;

    for (int i = 0; i < AUDIO_SAMPLES; i++) {
        float centered = (float)input[i] - mean;

        float filtered =
            HPF_ALPHA *
            (previous_output + centered - previous_input);

        previous_input = centered;
        previous_output = filtered;

        filtered_audio[i] = filtered;
    }
}


// FFT + power spectrum
static void calculate_spectrum(
    const float *frame,
    dsp_workspace_t *workspace
)
{
    // apply Hamming window
    for (int i = 0; i < FRAME_SIZE; i++) {
        workspace->fft_buffer[i].real =
            frame[i] * hamming_table[i];

        workspace->fft_buffer[i].imag = 0.0f;
    }

    // zero padding 400 -> 512
    for (int i = FRAME_SIZE; i < FFT_SIZE; i++) {
        workspace->fft_buffer[i].real = 0.0f;
        workspace->fft_buffer[i].imag = 0.0f;
    }

    fft(workspace->fft_buffer, FFT_SIZE);

    // calculate power
    for (int i = 0; i < FFT_BINS; i++) {
        float re = workspace->fft_buffer[i].real;
        float im = workspace->fft_buffer[i].imag;

        workspace->power_spectrum[i] =
            (re * re) + (im * im);
    }
}


// MFCC extraction
static void calculate_mfcc(
    const float *power_spectrum,
    float mfcc[MFCC_COUNT]
)
{
    float mel_energy[MEL_FILTERS];

    // mel filter bank
    for (int m = 0; m < MEL_FILTERS; m++) {
        int left = mel_bins[m];
        int right = mel_bins[m + 2];

        float energy = 0.0f;

        // use precomputed Mel-filter weights
        for (int k = left; k < right; k++) {
            energy +=
                power_spectrum[k] *
                mel_weight_table[m][k];
        }

        mel_energy[m] = logf(energy + EPSILON);
    }

    /*
     * DCT
     * skip coefficient 0 because RMS already provides overall signal energy
     */
    for (int c = 0; c < MFCC_COUNT; c++) {
        float result = 0.0f;

        for (int m = 0; m < MEL_FILTERS; m++) {
            result += mel_energy[m] * dct_table[c][m];
        }

        mfcc[c] = result;
    }
}


// extract 10 features from ONE 25 ms frame
static void extract_frame_features(
    const float *frame,
    float features[FRAME_FEATURES],
    dsp_workspace_t *workspace
)
{
    // RMS
    float sum_sq = 0.0f;

    for (int i = 0; i < FRAME_SIZE; i++) {
        sum_sq += frame[i] * frame[i];
    }

    float rms = sqrtf(sum_sq / FRAME_SIZE);

    // FFT
    calculate_spectrum(frame, workspace);

    // spectral features
    float weighted_sum = 0.0f;
    float magnitude_sum = 0.0f;

    float low_energy = 0.0f;
    float mid_energy = 0.0f;
    float high_energy = 0.0f;

    for (int bin = FIRST_BIN; bin <= LAST_BIN; bin++) {
        float power = workspace->power_spectrum[bin];
        float magnitude = sqrtf(power);

        // spectral centroid
        weighted_sum += frequency_table[bin] * magnitude;
        magnitude_sum += magnitude;

        // frequency bands
        if (bin < LOW_END_BIN) {
            low_energy += power;
        } else if (bin < MID_END_BIN) {
            mid_energy += power;
        } else {
            high_energy += power;
        }
    }

    float centroid = 0.0f;

    if (magnitude_sum > EPSILON) {
        centroid = weighted_sum / magnitude_sum;
    }

    // normalised band energy
    float total_energy =
        low_energy +
        mid_energy +
        high_energy +
        EPSILON;

    float low_ratio = low_energy / total_energy;
    float mid_ratio = mid_energy / total_energy;
    float high_ratio = high_energy / total_energy;

    // MFCC
    float mfcc[MFCC_COUNT];

    calculate_mfcc(
        workspace->power_spectrum,
        mfcc
    );

    // feature vector
    features[FEAT_RMS] = rms;
    features[FEAT_CENTROID] = centroid;
    features[FEAT_LOW_RATIO] = low_ratio;
    features[FEAT_MID_RATIO] = mid_ratio;
    features[FEAT_HIGH_RATIO] = high_ratio;

    for (int i = 0; i < MFCC_COUNT; i++) {
        features[FEAT_MFCC1 + i] = mfcc[i];
    }
}


// Core 1 processes the second half of the 48 audio frames
static void core1_entry(void)
{
    while (true) {
        uint32_t command = multicore_fifo_pop_blocking();

        if (command == CORE1_WORK_COMMAND) {
            for (int frame = NUM_FRAMES / 2;
                 frame < NUM_FRAMES;
                 frame++) {

                int offset = frame * HOP_SIZE;

                extract_frame_features(
                    &filtered_audio[offset],
                    all_frame_features[frame],
                    &workspace_core1
                );
            }

            multicore_fifo_push_blocking(CORE1_DONE_COMMAND);
        }
    }
}


/*
   aggregate 48 frames into final 20-value vector
   [0..9]   = feature means
   [10..19] = feature standard deviations

   Core 0 processes frames 0..23
   Core 1 processes frames 24..47
*/
static void build_feature_vector(float output[FINAL_FEATURES])
{
    // tell Core 1 to process frames 24..47
    multicore_fifo_push_blocking(CORE1_WORK_COMMAND);

    // Core 0 processes frames 0..23
    for (int frame = 0;
         frame < NUM_FRAMES / 2;
         frame++) {

        int offset = frame * HOP_SIZE;

        extract_frame_features(
            &filtered_audio[offset],
            all_frame_features[frame],
            &workspace_core0
        );
    }

    // wait until Core 1 finishes frames 24..47
    uint32_t response = multicore_fifo_pop_blocking();

    while (response != CORE1_DONE_COMMAND) {
        response = multicore_fifo_pop_blocking();
    }

    float sum[FRAME_FEATURES] = {0};
    float sum_squared[FRAME_FEATURES] = {0};

    // keep aggregation in original frame order
    for (int frame = 0; frame < NUM_FRAMES; frame++) {
        for (int f = 0; f < FRAME_FEATURES; f++) {
            float value = all_frame_features[frame][f];

            sum[f] += value;
            sum_squared[f] += value * value;
        }
    }

    for (int f = 0; f < FRAME_FEATURES; f++) {
        float mean = sum[f] / NUM_FRAMES;

        float variance =
            (sum_squared[f] / NUM_FRAMES) -
            (mean * mean);

        if (variance < 0.0f) {
            variance = 0.0f;
        }

        output[f] = mean;
        output[FRAME_FEATURES + f] = sqrtf(variance);
    }
}


// print csv
static void print_csv_header(void)
{
    printf(
        "sample_id,label,"
        "mean_rms,"
        "mean_centroid,"
        "mean_low_ratio,"
        "mean_mid_ratio,"
        "mean_high_ratio,"
        "mean_mfcc1,"
        "mean_mfcc2,"
        "mean_mfcc3,"
        "mean_mfcc4,"
        "mean_mfcc5,"
        "std_rms,"
        "std_centroid,"
        "std_low_ratio,"
        "std_mid_ratio,"
        "std_high_ratio,"
        "std_mfcc1,"
        "std_mfcc2,"
        "std_mfcc3,"
        "std_mfcc4,"
        "std_mfcc5\n"
    );
}

// export to csv
static void export_feature_vector_csv(
    const float vector[FINAL_FEATURES]
)
{
    sample_id++;

    // human-readable summary
    printf(
        "SUMMARY | RMS=%.3f | Centroid=%.1f Hz | "
        "Low=%.3f | Mid=%.3f | High=%.3f\n",
        vector[0],
        vector[1],
        vector[2],
        vector[3],
        vector[4]
    );

    // CSV row
    printf(
        "%lu,%s",
        (unsigned long)sample_id,
        DATASET_LABEL
    );

    for (int i = 0; i < FINAL_FEATURES; i++) {
        printf(",%.6f", vector[i]);
    }

    printf("\n");
}


// main
int main(void)
{
    stdio_init_all();

    // ADC + DMA setup
    init_dma_audio_capture();

    init_mel_filterbank();

    // initialise DSP lookup tables once
    // avoids repeated calculations during every 500 ms window
    init_hamming_table();
    init_fft_tables();
    init_dct_table();
    init_frequency_table();
    init_mel_weight_table();

    // launch Core 1 once; it waits for frame-processing commands
    multicore_launch_core1(core1_entry);

    sleep_ms(2000);

    printf("\nMOSAIC DSP - FINAL DMA + DUAL CORE\n");
    printf("Sampling rate : 16 kHz\n");
    printf("Window        : 500 ms\n");
    printf("Frame         : 25 ms\n");
    printf("Hop           : 10 ms\n");
    printf("FFT           : 512\n");
    printf("Frequency     : 125 - 7500 Hz\n");
    printf("MFCC          : 5\n");
    printf("Features      : 20\n");
    printf("Capture       : ADC FIFO + DMA ping-pong\n");
    printf("DSP           : RP2040 dual-core frame processing\n");
    printf("DSP tables    : precomputed Hamming / FFT / DCT / Mel weights\n\n");
    printf("Dataset label : %s\n\n", DATASET_LABEL);

    print_csv_header();

    /*
    first capture:
    fill raw_audio[0] before there is anything available to process
    */
    int process_buffer = 0;
    int capture_buffer = 1;

    start_dma_capture(raw_audio[process_buffer]);
    wait_for_capture();

    while (true) {
        /*
        immediately start capturing the next 500 ms window into the
        alternate buffer

        DMA in the background while both RP2040 cores process the
        previously completed buffer
        */
        start_dma_capture(raw_audio[capture_buffer]);

        uint64_t processing_start_us = time_us_64();

        // filter / preprocess the completed buffer
        preprocess_audio(raw_audio[process_buffer]);

        // extract DSP features using both RP2040 cores
        float feature_vector[FINAL_FEATURES];

        build_feature_vector(feature_vector);

        uint64_t processing_end_us = time_us_64();

        float processing_ms =
            (processing_end_us - processing_start_us) / 1000.0f;

        /*
        wait only if DSP finished before the next 500 ms DMA capture
        keep this wait to make the code safe if DSP becomes faster
        */
        uint64_t wait_start_us = time_us_64();

        wait_for_capture();

        uint64_t ready_us = time_us_64();

        float capture_wait_ms =
            (ready_us - wait_start_us) / 1000.0f;

        printf(
            "PROCESSING_TIME_MS=%.1f | CAPTURE_WAIT_MS=%.1f\n",
            processing_ms,
            capture_wait_ms
        );

        // send features for ML / dataset collection
        export_feature_vector_csv(feature_vector);

        // swap the two ping-pong buffers
        int tmp = process_buffer;
        process_buffer = capture_buffer;
        capture_buffer = tmp;
    }
}
