/* RP2040 PL011 UART1. No SDK runtime, IRQ handler or UART0 access.
 * Register offsets/flags match device/ser/sysdepend/rp2040/ser_sysdep.h.
 * The template initializes only UART0; UART1 is exclusively claimed in TEAM. */
#include "drv_uart1.h"
#include "../app.h"
#include <sys/sysdef.h>

#define UART1_REG(offset) (UINT32_C(0x40038000) + (offset))
#define FR_RXFE (1u << 4)
#define FR_TXFE (1u << 7)
#define FR_BUSY (1u << 3)

bool s3_uart1_init(void)
{
    /* Atomic reset aliases touch only UART1. Fixed small bound, no sensor wait. */
    out_w(RESETS_RESET + 0x2000u, RESETS_RESET_UART1);
    out_w(RESETS_RESET + 0x3000u, RESETS_RESET_UART1);
    unsigned n;
    for (n = 0; n < 256; ++n)
        if (in_w(RESETS_RESET_DONE) & RESETS_RESET_UART1) break;
    if (n == 256) return false;
    out_w(UART1_REG(0x30), 0);
    out_w(UART1_REG(0x38), 0); /* no UART IRQs */
    out_w(UART1_REG(0x44), 0x7ff);
    out_w(UART1_REG(0x48), 0); /* no UART DMA */
    /* divisor = clk_peri / (16*1200), Q6 rounded to nearest. */
    uint32_t divisor = (uint32_t)(((uint64_t)CLK_PERI_FREQ * 4u + 600u) / 1200u);
    out_w(UART1_REG(0x24), divisor >> 6);
    out_w(UART1_REG(0x28), divisor & 63u);
    out_w(UART1_REG(0x2c), (3u << 5) | (1u << 4)); /* 8N1, FIFO */
    clr_w(GPIO(8), GPIO_OD | GPIO_PUE | GPIO_PDE);
    set_w(GPIO(8), GPIO_IE);
    clr_w(GPIO(9), GPIO_OD | GPIO_PUE | GPIO_PDE);
    set_w(GPIO(9), GPIO_IE);
    out_w(GPIO_CTRL(8), GPIO_CTRL_FUNCSEL_UART);
    out_w(GPIO_CTRL(9), GPIO_CTRL_FUNCSEL_UART);
    out_w(UART1_REG(0x30), (1u << 9) | (1u << 8) | 1u);
    return true;
}

int s3_uart1_read(void)
{
    if (in_w(UART1_REG(0x18)) & FR_RXFE) return -1;
    uint32_t data = in_w(UART1_REG(0));
    if (data & 0xf00u) {
        out_w(UART1_REG(4), 0xf); /* clear framing/parity/break/overrun */
        return -2;
    }
    return (int)(data & 255u);
}

bool s3_uart1_send(const uint8_t command[5])
{
    uint32_t flags = in_w(UART1_REG(0x18));
    if ((flags & FR_BUSY) || !(flags & FR_TXFE)) return false;
    /* Five bytes fit in the empty 32-byte FIFO. Only this task writes. */
    for (unsigned i = 0; i < 5; ++i) out_w(UART1_REG(0), command[i]);
    return true;
}
