/* MMIO test boundary; production uses the template's sys/sysdef.h. */
#include <stdint.h>
uint32_t s3_test_read(uint32_t address);
void s3_test_write(uint32_t address, uint32_t value);
#define in_w(a) s3_test_read(a)
#define out_w(a,v) s3_test_write(a,v)
#define clr_w(a,v) out_w(a,in_w(a)&~(v))
#define set_w(a,v) out_w(a,in_w(a)|(v))
#define RESETS_RESET 0x4000c000u
#define RESETS_RESET_DONE 0x4000c008u
#define RESETS_RESET_UART1 (1u << 23)
#define GPIO(n) (0x4001c004u + 4u*(n))
#define GPIO_CTRL(n) (0x40014004u + 8u*(n))
#define GPIO_OD (1u << 7)
#define GPIO_IE (1u << 6)
#define GPIO_PUE (1u << 3)
#define GPIO_PDE (1u << 2)
#define GPIO_CTRL_FUNCSEL_UART 2u
#define CLK_PERI_FREQ 125000000u
