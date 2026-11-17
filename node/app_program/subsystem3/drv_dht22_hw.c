#include "drv_dht22.h"

#if TM_WIFI_CYW43
/* SDK namespace deliberately separate from kernel headers. The template
 * already links these SDK modules and supplies a kernel-backed claim lock.
 * Requires the real SDK 2.2/2.3 headers: template pico/version.h is hardcoded
 * to 2.1 and cannot be used to validate the installed SDK. */
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "dht22.pio.h"
#define DHT_PIN 2u

bool s3_dht_hw_init(s3_dht_t *d)
{
    PIO pio;
    /* SDK 2.x locks instruction-space search and insertion together. No
     * check-then-add race, fixed resource choice, or required=true panic. */
    if (!pio_claim_free_sm_and_add_program(&mosaic_dht22_program, &pio, &d->sm, &d->offset))
        return false;
    d->pio = pio;
    d->dma = dma_claim_unused_channel(false);
    if (d->dma < 0) {
        pio_remove_program_and_unclaim_sm(&mosaic_dht22_program, pio, d->sm, d->offset);
        return false;
    }
    dma_channel_set_irq0_enabled((unsigned)d->dma, false);
    dma_channel_set_irq1_enabled((unsigned)d->dma, false);
    dma_channel_acknowledge_irq0((unsigned)d->dma);
    dma_channel_acknowledge_irq1((unsigned)d->dma);
    gpio_init(DHT_PIN);
    gpio_pull_up(DHT_PIN);
    pio_sm_config c = mosaic_dht22_program_get_default_config(d->offset);
    sm_config_set_in_pins(&c, DHT_PIN);
    sm_config_set_jmp_pin(&c, DHT_PIN);
    sm_config_set_set_pins(&c, DHT_PIN, 1);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    uint32_t divider = (uint32_t)(((uint64_t)clock_get_hz(clk_sys) * 256u) / 2000000u);
    sm_config_set_clkdiv_int_frac(&c, (uint16_t)(divider >> 8), (uint8_t)divider);
    if (pio_sm_init(pio, d->sm, d->offset, &c) != 0) {
        dma_channel_unclaim((unsigned)d->dma);
        pio_remove_program_and_unclaim_sm(&mosaic_dht22_program, pio, d->sm, d->offset);
        return false;
    }
    pio_sm_set_consecutive_pindirs(pio, d->sm, DHT_PIN, 1, false);
    pio_gpio_init(pio, DHT_PIN); /* only after SM is disabled and pin released */
    return true;
}

void s3_dht_hw_start(s3_dht_t *d)
{
    PIO pio = d->pio;
    pio_sm_set_enabled(pio, d->sm, false);
    pio_sm_clear_fifos(pio, d->sm);
    pio_sm_restart(pio, d->sm);
    pio_sm_clkdiv_restart(pio, d->sm);
    pio_sm_exec(pio, d->sm, pio_encode_jmp(d->offset));
    dma_channel_config c = dma_channel_get_default_config((unsigned)d->dma);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, false);
    channel_config_set_write_increment(&c, true);
    channel_config_set_dreq(&c, pio_get_dreq(pio, d->sm, false));
    dma_channel_configure((unsigned)d->dma, &c, d->pulses, &pio->rxf[d->sm], 82, true);
    pio_sm_set_enabled(pio, d->sm, true);
}

int s3_dht_hw_result(s3_dht_t *d)
{
    if (dma_hw->ch[d->dma].ctrl_trig & DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS) return -1;
    if (dma_channel_is_busy((unsigned)d->dma)) return 0;
    return dma_hw->ch[d->dma].transfer_count == 0 ? 1 : -1;
}

void s3_dht_hw_stop(s3_dht_t *d)
{
    PIO pio = d->pio;
    pio_sm_set_enabled(pio, d->sm, false);
    pio_sm_restart(pio, d->sm);
    pio_sm_set_consecutive_pindirs(pio, d->sm, DHT_PIN, 1, false);
    dma_hw->abort = 1u << d->dma; /* asynchronous equivalent of SDK abort */
}

bool s3_dht_hw_stopped(s3_dht_t *d)
{
    /* RP2040-E13: ABORT can clear before the final bus write. The SDK's
     * dma_channel_abort() waits for BUSY, but spins without a time bound.
     * Poll the same condition in later task iterations instead. */
    if (dma_channel_is_busy((unsigned)d->dma)) return false;
    __compiler_memory_barrier();
    /* Both channel IRQ routes remain disabled throughout and after abort. */
    dma_channel_acknowledge_irq0((unsigned)d->dma);
    dma_channel_acknowledge_irq1((unsigned)d->dma);
    PIO pio = d->pio;
    /* W1C bus-error bits through the non-trigger alias, with EN cleared. */
    dma_hw->ch[d->dma].al1_ctrl =
        (dma_hw->ch[d->dma].ctrl_trig & ~DMA_CH0_CTRL_TRIG_EN_BITS) |
        DMA_CH0_CTRL_TRIG_READ_ERROR_BITS | DMA_CH0_CTRL_TRIG_WRITE_ERROR_BITS;
    pio_sm_clear_fifos(pio, d->sm);
    pio_sm_restart(pio, d->sm);
    pio_sm_exec(pio, d->sm, pio_encode_jmp(d->offset));
    return true;
}
#else
/* This build profile does not link the shared SDK allocator/PIO/DMA modules.
 * Explicit capability failure, never synthetic samples or bit-banging. */
bool s3_dht_hw_init(s3_dht_t *d) { (void)d; return false; }
void s3_dht_hw_start(s3_dht_t *d) { (void)d; }
int s3_dht_hw_result(s3_dht_t *d) { (void)d; return -1; }
void s3_dht_hw_stop(s3_dht_t *d) { (void)d; }
bool s3_dht_hw_stopped(s3_dht_t *d) { (void)d; return true; }
#endif
