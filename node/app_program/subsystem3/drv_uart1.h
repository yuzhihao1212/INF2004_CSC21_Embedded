#ifndef S3_DRV_UART1_H
#define S3_DRV_UART1_H
#include <stdbool.h>
#include <stdint.h>
/* Environment task only. read: -1 empty, -2 UART error, otherwise byte. */
bool s3_uart1_init(void);
int s3_uart1_read(void);
bool s3_uart1_send(const uint8_t command[5]);
#endif
