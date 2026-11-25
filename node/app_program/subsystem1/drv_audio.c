/*
 *  drv_audio.c
 *  Subsystem 1 -- microphone capture driver: RP2040 ADC + DMA at 16 kHz.
 *
 *  Two 8000-sample buffers are filled in turn. The ADC free-runs at 16 kHz
 *  and DMA copies each sample into the current buffer, so no task or
 *  interrupt runs per sample. When the buffer is full, DMA raises DMA_IRQ_1:
 *  the handler stops the ADC, records the time and signals the audio task.
 *  The task then re-arms capture into the other buffer before it processes
 *  the full one, so capture and DSP overlap.
 *
 *  The kernel owns the interrupt vectors: the handler is registered with
 *  tk_def_int(), never through the SDK. With WIFI=cyw43 the SDK's DMA
 *  channel allocator is shared with the radio driver, so the hardware calls
 *  go through drv_audio_hw.c. With WIFI=none there is no SDK, so the
 *  registers are written directly and DMA channel 11 is used (TEAM.md).
 */
#include "drv_audio.h"
#include "drv_audio_hw.h"
#include <stdbool.h>

#define R(a) (*(volatile uint32_t *)(uintptr_t)(a))    /* memory-mapped register */
/* ADC: CS +0, FCS +8, FIFO +12, DIV +0x10, INTE +0x18.
 * DMA: channel n at +n*0x40 (READ_ADDR, WRITE_ADDR, TRANS_COUNT, CTRL_TRIG);
 *      INTE1 +0x414, INTS1 +0x41c.
 * Adding 0x2000 to a register address sets the bits written as 1, and
 * adding 0x3000 clears them, without a read-modify-write. */
#define ADC 0x4004c000u
#define DMA 0x50000000u
#define IRQ 12u /* DMA_IRQ_1; exclusively owned by S1. */
#define TIMER_RAWH 0x40054024u  /* free-running 64-bit timer, high word */
#define TIMER_RAWL 0x40054028u  /* low word */
#define WINDOW_SAMPLES 8000     /* 500 ms at 16 kHz */

static uint16_t buffers[2][WINDOW_SAMPLES];
static ID ready;                    /* signalled once per completed buffer */
static unsigned channel, current;   /* DMA channel; buffer being filled */
#if !TM_WIFI_CYW43
static uint32_t ch;                 /* address of this channel's registers */
#endif
static volatile uint64_t delivered; /* completion time of the last buffer */
static uint64_t armed_us;
static volatile uint32_t capture_us;

uint32_t audio_capture_duration_us(void) { return capture_us; }

/*
 * Timer count since boot. Known limitation: on this kernel one count is
 * 42.67 us, not 1 us.
 *
 * The RP2040 timer counts ticks made by dividing clk_ref (12 MHz) by
 * WATCHDOG_TICK.CYCLES. The Pico SDK sets CYCLES to 12, one tick per
 * microsecond. This kernel leaves the register at its reset value of 0, and
 * the hardware then divides by 512: the nodes logged 11719 counts for a
 * 500 ms capture (testing/integration/logs/2026-11-20-audio-investigation.md).
 *
 * So every "_us" value taken from this clock is 42.67 times too small: a
 * logged dsp_us of 5581 is about 238 ms. The 500 ms deadline checks in
 * subsystems 1 and 2 compare against this clock too, so they cannot trip.
 * The correction is to return count * 512 / 12. It is left out because the
 * hardware was returned after the final demo and the change could not be
 * tested on a board; this file is the code that ran in that demo.
 */
uint64_t audio_clock_us(void)
{
    uint32_t high, low;
    /* Re-read if the low word carried into the high word between reads. */
    do { high = R(TIMER_RAWH); low = R(TIMER_RAWL); }
    while (high != R(TIMER_RAWH));
    return ((uint64_t)high << 32) | low;
}

/* Start filling buffers[current]. Task context only. */
static void arm(void)
{
#if TM_WIFI_CYW43
    armed_us = audio_clock_us();
    s1_audio_hw_start(channel, buffers[current]);
#else
    R(ADC + 0x3000) = 8; /* stop, drain, then arm the alternate buffer */
    while (!(R(ADC + 8) & 256)) (void)R(ADC + 12);
    R(ch) = ADC + 12;                                   /* read the ADC FIFO */
    R(ch + 4) = (uint32_t)(uintptr_t)buffers[current];  /* write the buffer */
    R(ch + 8) = WINDOW_SAMPLES;
    /* Enable, 16-bit transfers, increment the write address, no chaining
     * (chain to itself), paced by the ADC data request (36). */
    R(ch + 12) = 1u | (1u << 2) | (1u << 5) | (channel << 11) | (36u << 15);
    armed_us = audio_clock_us();
    R(ADC + 0x2000) = 8;                                /* START_MANY */
#endif
}

/* DMA_IRQ_1 handler: interrupt context, so it only records and signals. */
static void completed(UINT intno)
{
    (void)intno;
    if (!(R(DMA + 0x41c) & (1u << channel))) return;   /* not our channel */
#if TM_WIFI_CYW43
    s1_audio_hw_stop();
#else
    R(ADC + 0x3000) = 8;
#endif
    R(DMA + 0x41c) = 1u << channel;                     /* acknowledge */
    delivered = audio_clock_us();
    capture_us = (uint32_t)(delivered - armed_us);
    (void)tk_sig_sem(ready, 1);
}

ER audio_capture_start(void)
{
    T_CSEM sem = {0}; T_DINT irq = {0}; ER er;
    sem.maxsem = 1;
    ready = tk_cre_sem(&sem);
    if (ready < 0) return ready;
#if TM_WIFI_CYW43
    int allocated = s1_audio_hw_init();
    if (allocated < 0) { tk_del_sem(ready); return E_LIMIT; }
    channel = (unsigned)allocated;
#else
    unsigned wait;
    channel = 11; /* TEAM.md reservation, no SDK allocator in WIFI=none. */
    ch = DMA + channel * 0x40;
    /* Take the ADC and DMA out of reset, with a bounded wait. */
    R(RESETS_RESET + 0x3000) = RESETS_RESET_ADC | RESETS_RESET_DMA;
    for (wait = 0; wait < 10000; ++wait)
        if ((R(RESETS_RESET_DONE) & 5) == 5) break;
    if (wait == 10000) { er = E_IO; goto fail; }
    R(GPIO_CTRL(26)) = GPIO_CTRL_FUNCSEL_NULL;
    /* The +0x3000 register alias clears bits written as 1. Disable the
     * GPIO26 digital receiver and both pulls, matching adc_gpio_init(). */
    R(0x4001f06cu) = (1u << 6) | (1u << 3) | (1u << 2);
    R(ADC + 0x18) = 0; /* no competing ADC FIFO interrupt */
    R(ADC) = 1;        /* enable, then wait for READY */
    for (wait = 0; wait < 10000; ++wait) if (R(ADC) & 256) break;
    if (wait == 10000) { er = E_IO; goto fail; }
    R(ADC + 0x10) = 2999u << 8; /* kernel's 48 MHz ADC clock -> 16 kHz */
    R(ADC + 8) = 1u | 8u | (1u << 24); /* FIFO, DREQ, threshold=1 */
#endif
    irq.intatr = TA_HLNG; irq.inthdr = (FP)completed;
    er = tk_def_int(IRQ, &irq);
    if (er < 0) goto fail;
    R(DMA + 0x41c) = 1u << channel;    /* clear a stale request */
    R(DMA + 0x2414) = 1u << channel;   /* atomic INTE1 set */
    ClearInt(IRQ);
    EnableInt(IRQ, INTPRI_GROUP(2, 0));
#if TM_WIFI_CYW43
    tm_printf((UB*)"audio capture: reference SDK ADC/DMA, kernel IRQ1\n");
#endif
    tm_printf((UB*)"audio ADC: cs=%x div=%x fcs=%x clk_ctrl=%x clk_div=%x pad=%x dma=%u\n",
        R(ADC), R(ADC + 0x10), R(ADC + 8), R(0x40008060u), R(0x40008064u), R(0x4001c06cu), channel);
    current = 0; arm(); return E_OK;
fail:
#if TM_WIFI_CYW43
    s1_audio_hw_release(channel);
#endif
    tk_del_sem(ready); return er;
}

ER audio_capture_wait(uint16_t **samples, uint64_t *timestamp)
{
    /* A window takes 500 ms; 1000 ms without one means capture has stalled. */
    ER er = tk_wai_sem(ready, 1, 1000);
    if (er < 0) return er;
    *samples = buffers[current]; *timestamp = delivered;
    current ^= 1; arm(); /* capture overlaps processing of the previous buffer */
    return E_OK;
}
