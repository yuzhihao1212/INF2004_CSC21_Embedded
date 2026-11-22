#include "drv_audio_hw.h"

#if TM_WIFI_CYW43
/* Keep SDK types separate from the kernel header namespace, as S3 does.
 * This is the reference firmware/audio/audio_capture.c ADC/DMA setup.
 * No SDK IRQ registration: completion remains a micro T-Kernel handler. */
#include "hardware/adc.h"
#include "hardware/dma.h"

static dma_channel_config capture_config;

int s1_audio_hw_init(void)
{
    adc_init();
    adc_gpio_init(26);
    adc_select_input(0);
    adc_fifo_setup(true, true, 1, false, false);
    adc_hw->div = 2999u << ADC_DIV_INT_LSB; /* 48 MHz / 16 kHz, integer. */

    int channel = dma_claim_unused_channel(false);
    if (channel < 0) return channel;
    capture_config = dma_channel_get_default_config((unsigned)channel);
    channel_config_set_transfer_data_size(&capture_config, DMA_SIZE_16);
    channel_config_set_read_increment(&capture_config, false);
    channel_config_set_write_increment(&capture_config, true);
    channel_config_set_dreq(&capture_config, DREQ_ADC);
    dma_channel_set_irq0_enabled((unsigned)channel, false);
    dma_channel_set_irq1_enabled((unsigned)channel, false);
    dma_channel_acknowledge_irq0((unsigned)channel);
    dma_channel_acknowledge_irq1((unsigned)channel);
    return channel;
}

void s1_audio_hw_start(unsigned channel, uint16_t *destination)
{
    adc_run(false);
    adc_fifo_drain();
    dma_channel_configure(channel, &capture_config, destination,
                          &adc_hw->fifo, 8000, true);
    adc_run(true);
}

void s1_audio_hw_stop(void)
{
    adc_run(false);
    adc_fifo_drain();
}

void s1_audio_hw_release(unsigned channel)
{
    adc_run(false);
    dma_channel_set_irq1_enabled(channel, false);
    dma_channel_unclaim(channel);
}
#endif
