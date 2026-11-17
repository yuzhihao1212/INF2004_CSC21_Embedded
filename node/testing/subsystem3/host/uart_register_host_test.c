#include "drv_uart1.h"
#include <assert.h>
#include <stdio.h>
#include <sys/sysdef.h>
static uint32_t uart[20], flags, data, tx[5], writes;
static bool reset_ready;
uint32_t s3_test_read(uint32_t a)
{
    if (a==RESETS_RESET_DONE) return reset_ready ? RESETS_RESET_UART1 : 0;
    if (a==0x40038018u) return flags;
    if (a==0x40038000u) return data;
    if (a>=0x40038000u && a<=0x40038048u) return uart[(a-0x40038000u)/4];
    assert(a==GPIO(8) || a==GPIO(9)); return 0;
}
void s3_test_write(uint32_t a,uint32_t v)
{
    /* Any attempt to touch UART0 or an unclaimed pin fails this test. */
    if (a==RESETS_RESET+0x2000u || a==RESETS_RESET+0x3000u) { assert(v==RESETS_RESET_UART1); return; }
    if (a==GPIO(8) || a==GPIO(9)) return;
    if (a==GPIO_CTRL(8) || a==GPIO_CTRL(9)) { assert(v==2); return; }
    assert(a>=0x40038000u && a<=0x40038048u);
    if (a==0x40038000u) { assert(writes<5); tx[writes++]=v; }
    else uart[(a-0x40038000u)/4]=v;
}
int main(void)
{
    assert(!s3_uart1_init()); reset_ready=true; assert(s3_uart1_init());
    assert(uart[0x24/4]==6510 && uart[0x28/4]==27);
    assert(uart[0x2c/4]==0x70 && uart[0x30/4]==0x301);
    assert(uart[0x38/4]==0 && uart[0x48/4]==0);
    flags=1u<<4; assert(s3_uart1_read()==-1);
    flags=0; data=0x352; assert(s3_uart1_read()==-2 && uart[1]==15);
    data=0xa6; assert(s3_uart1_read()==0xa6);
    const uint8_t command[]={0xfe,0xa6,0,1,0xa7};
    assert(!s3_uart1_send(command));
    flags=(1u<<7)|(1u<<3); assert(!s3_uart1_send(command));
    flags=1u<<7; assert(s3_uart1_send(command) && writes==5);
    for(unsigned i=0;i<5;++i) assert(tx[i]==command[i]);
    puts("PASS S3-U12: actual UART driver register accesses, divisor, FIFO and errors; no UART0 writes");
}
