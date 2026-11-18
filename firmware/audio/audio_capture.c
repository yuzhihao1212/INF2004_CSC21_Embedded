#include "audio_capture.h"
#include "audio_dsp.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/structs/adc.h"
/* GP26 ADC0. AUD -> GP26, mic GND -> GND, VCC -> 3V3. */
#define MIC_PIN 26
#define MIC_ADC_INPUT 0
#define SAMPLE_RATE AUDIO_DSP_SAMPLE_RATE
#define AUDIO_SAMPLES AUDIO_DSP_WINDOW_SAMPLES
#define ADC_CLOCK_HZ 48000000u
#define ADC_CLKDIV_INTEGER ((ADC_CLOCK_HZ / SAMPLE_RATE) - 1u)
static uint16_t raw_audio[2][AUDIO_SAMPLES];
static uint dma_chan;
static dma_channel_config dma_cfg;
static volatile bool capture_done = false;
static bool audio_initialized = false;
static int processing_buffer = 0;
static int filling_buffer = 1;
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
    adc_fifo_setup(true, true, 1, false, false);

    // fixed 16 kHz ADC conversion-start rate
    adc_hw->div = ADC_CLKDIV_INTEGER << ADC_DIV_INT_LSB;

    dma_chan = dma_claim_unused_channel(true);
    dma_cfg = dma_channel_get_default_config(dma_chan);

    // ADC FIFO: 16-bit read; destination buffer increments
    channel_config_set_transfer_data_size(&dma_cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&dma_cfg, false);
    channel_config_set_write_increment(&dma_cfg, true);

    // pace DMA transfers using ADC FIFO requests
    channel_config_set_dreq(&dma_cfg, DREQ_ADC);

    // use DMA IRQ 0 to know when 8000 samples have been captured
    dma_channel_set_irq0_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_handler);
    irq_set_enabled(DMA_IRQ_0, true);
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


void audio_capture_init(void)
{
    if (audio_initialized) return;
    init_dma_audio_capture();
    processing_buffer = 0;
    filling_buffer = 1;
    start_dma_capture(raw_audio[processing_buffer]);
    audio_initialized = true;
}

const uint16_t *audio_capture_next_window(void)
{
    if (!audio_initialized) return NULL;
    wait_for_capture();
    const uint16_t *completed = raw_audio[processing_buffer];
    // Begin capturing a new 500 ms window while caller processes this one.
    start_dma_capture(raw_audio[filling_buffer]);
    int tmp = processing_buffer;
    processing_buffer = filling_buffer;
    filling_buffer = tmp;
    return completed;
}
