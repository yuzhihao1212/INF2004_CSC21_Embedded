/* RP2040 ADC/DMA driver. Kernel owns vectors; no SDK IRQ registration. */
#include "drv_audio.h"
#include "drv_audio_hw.h"
#include <stdbool.h>
#define R(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define ADC 0x4004c000u
#define DMA 0x50000000u
#define IRQ 12u /* DMA_IRQ_1; exclusively owned by S1. */
static uint16_t buffers[2][8000];
static ID ready;
static unsigned channel, current;
#if !TM_WIFI_CYW43
static uint32_t ch;
#endif
static volatile uint64_t delivered;
static uint64_t armed_us;
static volatile uint32_t capture_us;

uint32_t audio_capture_duration_us(void) { return capture_us; }

uint64_t audio_clock_us(void)
{
    uint32_t high, low;
    do { high=R(0x40054024u); low=R(0x40054028u); }
    while (high!=R(0x40054024u));
    return ((uint64_t)high<<32)|low;
}
static void arm(void)
{
#if TM_WIFI_CYW43
    armed_us=audio_clock_us();
    s1_audio_hw_start(channel,buffers[current]);
#else
    R(ADC+0x3000)=8; /* stop, drain, then arm the alternate buffer */
    while (!(R(ADC+8)&256)) (void)R(ADC+12);
    R(ch)=ADC+12;
    R(ch+4)=(uint32_t)(uintptr_t)buffers[current];
    R(ch+8)=8000;
    R(ch+12)=1u|(1u<<2)|(1u<<5)|(channel<<11)|(36u<<15);
    armed_us=audio_clock_us();
    R(ADC+0x2000)=8;
#endif
}
static void completed(UINT intno)
{
    (void)intno;
    if (!(R(DMA+0x41c)&(1u<<channel))) return;
#if TM_WIFI_CYW43
    s1_audio_hw_stop();
#else
    R(ADC+0x3000)=8;
#endif
    R(DMA+0x41c)=1u<<channel;
    delivered=audio_clock_us();
    capture_us=(uint32_t)(delivered-armed_us);
    (void)tk_sig_sem(ready,1);
}
ER audio_capture_start(void)
{
    T_CSEM sem={0}; T_DINT irq={0}; ER er;
    sem.maxsem=1;
    ready=tk_cre_sem(&sem);
    if (ready<0) return ready;
#if TM_WIFI_CYW43
    int allocated=s1_audio_hw_init();
    if (allocated<0) { tk_del_sem(ready); return E_LIMIT; }
    channel=(unsigned)allocated;
#else
    unsigned wait;
    channel=11; /* TEAM.md reservation, no SDK allocator in WIFI=none. */
    ch=DMA+channel*0x40;
    R(RESETS_RESET+0x3000)=RESETS_RESET_ADC|RESETS_RESET_DMA;
    for (wait=0;wait<10000;++wait)
        if ((R(RESETS_RESET_DONE)&5)==5) break;
    if (wait==10000) { er=E_IO; goto fail; }
    R(GPIO_CTRL(26))=GPIO_CTRL_FUNCSEL_NULL;
    /* The +0x3000 register alias clears bits written as 1. Disable the
     * GPIO26 digital receiver and both pulls, matching adc_gpio_init(). */
    R(0x4001f06cu)=(1u<<6)|(1u<<3)|(1u<<2);
    R(ADC+0x18)=0; /* no competing ADC FIFO interrupt */
    R(ADC)=1;
    for (wait=0;wait<10000;++wait) if (R(ADC)&256) break;
    if (wait==10000) { er=E_IO; goto fail; }
    R(ADC+0x10)=2999u<<8; /* kernel's 48 MHz ADC clock -> 16 kHz */
    R(ADC+8)=1u|8u|(1u<<24); /* FIFO, DREQ, threshold=1 */
#endif
    irq.intatr=TA_HLNG; irq.inthdr=(FP)completed;
    er=tk_def_int(IRQ,&irq);
    if (er<0) goto fail;
    R(DMA+0x41c)=1u<<channel;
    R(DMA+0x2414)=1u<<channel; /* atomic INTE1 set */
    ClearInt(IRQ);
    EnableInt(IRQ,INTPRI_GROUP(2,0));
#if TM_WIFI_CYW43
    tm_printf((UB*)"audio capture: reference SDK ADC/DMA, kernel IRQ1\n");
#endif
    tm_printf((UB*)"audio ADC: cs=%x div=%x fcs=%x clk_ctrl=%x clk_div=%x pad=%x dma=%u\n",
        R(ADC),R(ADC+0x10),R(ADC+8),R(0x40008060u),R(0x40008064u),R(0x4001c06cu),channel);
    current=0; arm(); return E_OK;
fail:
#if TM_WIFI_CYW43
    s1_audio_hw_release(channel);
#endif
    tk_del_sem(ready); return er;
}
ER audio_capture_wait(uint16_t **samples,uint64_t *timestamp)
{
    ER er=tk_wai_sem(ready,1,1000);
    if (er<0) return er;
    *samples=buffers[current]; *timestamp=delivered;
    current^=1; arm(); /* capture overlaps processing of the previous buffer */
    return E_OK;
}
