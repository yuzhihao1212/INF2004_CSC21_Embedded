#ifndef S3_DRV_PIR_H
#define S3_DRV_PIR_H
#include "../app.h"
/* Only the S3 environment task may call this GPIO driver. */
ER s3_pir_init(void);
BOOL s3_pir_read(void);
#endif
