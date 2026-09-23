#include <stdio.h>
#include <inttypes.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"

#define MIC_PIN 26
#define MIC_ADC_INPUT 0
#define SAMPLE_WINDOW_MS 100
#define ADC_REFERENCE_VOLTS 3.3f

// Example starting points in ADC counts, NOT calibrated loudness limits.
// Observe quiet-room and speech readings with your own breakout, then tune
// these for its gain, distance, background noise, and classroom environment.
#define SOUND_THRESHOLD_P2P 80
#define LOUD_THRESHOLD_P2P 300

#if SOUND_THRESHOLD_P2P >= LOUD_THRESHOLD_P2P
#error "SOUND_THRESHOLD_P2P must be less than LOUD_THRESHOLD_P2P"
#endif

int main(void) {
    // CMake routes printf() to USB and disables UART stdio.
    stdio_init_all();

    // Follow the SDK hello_adc example: initialise the ADC, disable digital
    // functions/pulls on GP26, then select its ADC channel (input 0).
    adc_init();
    adc_gpio_init(MIC_PIN);
    adc_select_input(MIC_ADC_INPUT);

    sleep_ms(2000); // Give USB serial time to initialise.
    printf("Analog microphone test: GP26 / ADC0\n");
    printf("100 ms windows; raw value is the LAST sample, not loudness.\n");
    printf("Tune peak-to-peak thresholds for your microphone and room.\n");
    printf("Sound threshold: %u | Loud threshold: %u ADC counts\n",
           (unsigned int)SOUND_THRESHOLD_P2P, (unsigned int)LOUD_THRESHOLD_P2P);
    printf("Timestamps are milliseconds since Pico boot.\n");

    while (true) {
        uint16_t minimum = 4095;
        uint16_t maximum = 0;
        uint16_t raw_value;
        absolute_time_t window_end = make_timeout_time_ms(SAMPLE_WINDOW_MS);

        // Read repeatedly for one window without serial printing between
        // samples. This simple polling test does not guarantee a fixed
        // audio sample rate. The next window starts after its summary prints.
        do {
            raw_value = adc_read();
            if (raw_value < minimum) {
                minimum = raw_value;
            }
            if (raw_value > maximum) {
                maximum = raw_value;
            }
        } while (!time_reached(window_end));

        // Subtracting extrema removes the DC bias from this amplitude estimate.
        // Peak-to-peak is sensitive to spikes and is not a calibrated dB SPL value.
        uint16_t peak_to_peak = maximum - minimum;
        const char *sound_state;
        if (peak_to_peak >= LOUD_THRESHOLD_P2P) {
            sound_state = "LOUD SOUND";
        } else if (peak_to_peak >= SOUND_THRESHOLD_P2P) {
            sound_state = "SOUND DETECTED";
        } else {
            sound_state = "QUIET";
        }

        // Approximate voltage of the last sample, using the requested formula.
        // Actual accuracy depends on the board's ADC reference and ADC noise.
        float voltage = raw_value * ADC_REFERENCE_VOLTS / 4095.0f;
        uint64_t elapsed_ms = time_us_64() / 1000;

        // One summary per window (about ten per second), never every sample.
        printf("[%" PRIu64 " ms] ADC raw: %u | Voltage: %.2f V | "
               "Min: %u | Max: %u | Peak-to-Peak: %u | %s\n",
               elapsed_ms, (unsigned int)raw_value, voltage,
               (unsigned int)minimum, (unsigned int)maximum,
               (unsigned int)peak_to_peak, sound_state);
    }
}
