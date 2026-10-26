#include "dht22.h"
#include "dht22.pio.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "pico/stdlib.h"

bool dht22_init(dht22_t *d, unsigned pin) {
    *d = (dht22_t){.sm = -1, .dma = -1, .pin = pin};
    gpio_init(pin); gpio_pull_up(pin);
    PIO choices[] = {pio0, pio1};
    for (unsigned i = 0; i < 2; ++i) {
        if (!pio_can_add_program(choices[i], &mosaic_dht22_program)) continue;
        int sm = pio_claim_unused_sm(choices[i], false);
        if (sm < 0) continue;
        d->pio = choices[i]; d->sm = sm;
        break;
    }
    if (d->sm < 0) return false;
    d->dma = dma_claim_unused_channel(false);
    if (d->dma < 0) {
        pio_sm_unclaim(d->pio, (unsigned)d->sm);
        d->sm = -1;
        return false;
    }
    /* Claiming does not reset a channel's previous IRQ configuration. This
     * driver polls; isolate only our channel from shared/audio DMA IRQs. */
    dma_channel_set_irq0_enabled((unsigned)d->dma, false);
    dma_channel_set_irq1_enabled((unsigned)d->dma, false);
    dma_channel_acknowledge_irq0((unsigned)d->dma);
    dma_channel_acknowledge_irq1((unsigned)d->dma);
    d->offset = pio_add_program(d->pio, &mosaic_dht22_program);
    pio_gpio_init(d->pio, pin);
    pio_sm_config c = mosaic_dht22_program_get_default_config(d->offset);
    sm_config_set_in_pins(&c, pin);
    sm_config_set_jmp_pin(&c, pin);
    sm_config_set_set_pins(&c, pin, 1);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    /* Q8 divider uses integer arithmetic; floor error < 1/256 system cycle.
     * At default 125 MHz this is exactly 62.5 => 2 MHz PIO clock. */
    uint32_t divider_x256 = (uint32_t)(((uint64_t)clock_get_hz(clk_sys) * 256) / 2000000);
    sm_config_set_clkdiv_int_frac(&c, (uint16_t)(divider_x256 >> 8), (uint8_t)divider_x256);
    pio_sm_init(d->pio, (unsigned)d->sm, d->offset, &c);
    pio_sm_set_consecutive_pindirs(d->pio, (unsigned)d->sm, pin, 1, false);
    d->ready = true;
    return true;
}

bool dht22_start(dht22_t *d) {
    if (!d->ready || d->active) return false;
    unsigned sm = (unsigned)d->sm;
    pio_sm_set_enabled(d->pio, sm, false);
    pio_sm_clear_fifos(d->pio, sm);
    pio_sm_restart(d->pio, sm);
    pio_sm_clkdiv_restart(d->pio, sm);
    pio_sm_exec(d->pio, sm, pio_encode_jmp(d->offset));
    dma_channel_config c = dma_channel_get_default_config((unsigned)d->dma);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, false);
    channel_config_set_write_increment(&c, true);
    channel_config_set_dreq(&c, pio_get_dreq(d->pio, sm, false));
    dma_channel_configure((unsigned)d->dma, &c, d->pulses, &d->pio->rxf[sm], 82, true);
    d->started_us = time_us_64(); d->active = true;
    pio_sm_set_enabled(d->pio, sm, true);
    return true;
}

bool dht22_service(dht22_t *d, environment_record_t *r) {
    if (!d->active) return false;
    bool complete = !dma_channel_is_busy((unsigned)d->dma);
    if (!complete && time_us_64() - d->started_us < 10000) return false;
    pio_sm_set_enabled(d->pio, (unsigned)d->sm, false);
    dma_channel_abort((unsigned)d->dma);
    /* RP2040 abort can leave a completion IRQ pending (SDK E13 guidance).
     * Both IRQ routes stay disabled for this polling channel. */
    dma_channel_acknowledge_irq0((unsigned)d->dma);
    dma_channel_acknowledge_irq1((unsigned)d->dma);
    pio_sm_clear_fifos(d->pio, (unsigned)d->sm);
    pio_sm_restart(d->pio, (unsigned)d->sm);
    pio_sm_set_consecutive_pindirs(d->pio, (unsigned)d->sm, d->pin, 1, false);
    pio_sm_exec(d->pio, (unsigned)d->sm, pio_encode_jmp(d->offset));
    d->active = false;
    uint8_t bytes[5]; int16_t temperature = 0; uint16_t humidity = 0;
    sensor_status_t s = SENSOR_TIMEOUT;
    if (complete) {
        s = environment_decode_dht_pulses(d->pulses, bytes);
        if (s == SENSOR_OK) s = environment_decode_dht(bytes, &temperature, &humidity);
    }
    /* Record updates happen now; the valid sample itself dates from capture
     * start. Do not move the record timestamp behind other sensor updates. */
    environment_apply_dht(r, s, temperature, humidity, (uint32_t)(time_us_64() / 1000));
    if (s == SENSOR_OK) r->dht_sample_ms = (uint32_t)(d->started_us / 1000);
    return true;
}
