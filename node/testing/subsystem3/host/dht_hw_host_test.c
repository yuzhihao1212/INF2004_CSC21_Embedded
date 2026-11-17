#include "drv_dht22.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include <assert.h>
#include <stdio.h>

static mock_dma_hw registers;
mock_dma_hw *dma_hw = &registers;
unsigned mock_fifo_clears, mock_pio_disables, mock_releases, mock_ack0, mock_ack1;

int main(void)
{
    struct { uint32_t rxf[4]; } pio = {0};
    s3_dht_t d = {.pio=&pio, .sm=1, .offset=3, .dma=4};
    registers.ch[4].ctrl_trig = DMA_CH0_CTRL_TRIG_BUSY_BITS | DMA_CH0_CTRL_TRIG_EN_BITS;
    s3_dht_hw_stop(&d);
    assert(registers.abort == (1u << 4));
    assert(mock_pio_disables == 1 && mock_releases == 1);
    registers.abort = 0; /* E13: ABORT clears while a write is still in flight. */
    assert(!s3_dht_hw_stopped(&d));
    assert(mock_ack0 == 0 && mock_ack1 == 0 && mock_fifo_clears == 0);
    registers.ch[4].ctrl_trig = DMA_CH0_CTRL_TRIG_EN_BITS;
    assert(s3_dht_hw_stopped(&d));
    assert(mock_ack0 == 1 && mock_ack1 == 1 && mock_fifo_clears == 1);
    assert(!(registers.ch[4].al1_ctrl & DMA_CH0_CTRL_TRIG_EN_BITS));
    puts("PASS S3-U21: actual hardware boundary waits for BUSY after ABORT clears (register double)");
    return 0;
}
