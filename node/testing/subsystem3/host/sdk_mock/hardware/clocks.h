#ifndef S3_MOCK_CLOCKS_H
#define S3_MOCK_CLOCKS_H
#include <stdint.h>
enum { clk_sys };
static inline uint32_t clock_get_hz(int c) {(void)c;return 125000000;}
#endif
