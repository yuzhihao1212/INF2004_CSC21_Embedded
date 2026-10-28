/* Isolation recorder: GP26/ADC0, 16 kHz/8000-sample ADC settings.
 * Capture stops BEFORE USB transmission. No DSP, classifier or core-1 worker.
 * Gaps between 500 ms blocks are intentional; not live VAD firmware.
 */
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/structs/adc.h"
#include "audio_raw_diagnostic.h"

static uint16_t samples[8000];

static void write_raw(const char *data, size_t count) {
    fwrite(data, 1, count, stdout);
    fflush(stdout);
}

int main(void) {
    stdio_init_all();
    adc_init();
    adc_gpio_init(26);
    adc_select_input(0);
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(2999.0f);
    uint channel = dma_claim_unused_channel(true);
    dma_channel_config config = dma_channel_get_default_config(channel);
    channel_config_set_transfer_data_size(&config, DMA_SIZE_16);
    channel_config_set_read_increment(&config, false);
    channel_config_set_write_increment(&config, true);
    channel_config_set_dreq(&config, DREQ_ADC);
    uint32_t window = 0;
    unsigned remaining = 0;
    while (true) {
        int command = getchar_timeout_us(remaining ? 0 : 1000);
        if (command == 'r') {
            remaining = AUDIO_RAW_DIAGNOSTIC_BLOCKS;
            puts("RAW_READY,16");
        } else if (command == 'v') {
            remaining = 0;
            puts("RAW_DONE");
        }
        if (!remaining) continue;
        adc_run(false);
        adc_fifo_drain();
        dma_channel_configure(channel, &config, samples, &adc_hw->fifo, 8000, true);
        adc_run(true);
        dma_channel_wait_for_finish_blocking(channel);
        adc_run(false);
        adc_fifo_drain();
        uint64_t delivered = time_us_64();
        /* -1 is explicitly 'no board model', not a speech probability. */
        audio_raw_diagnostic_emit(samples, ++window, delivered, -1.0f, -1.0f, write_raw);
        if (!--remaining) puts("RAW_DONE");
    }
}
