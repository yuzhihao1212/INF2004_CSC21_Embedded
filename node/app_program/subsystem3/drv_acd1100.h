#ifndef S3_DRV_ACD1100_H
#define S3_DRV_ACD1100_H
#include "acd1100_protocol.h"
typedef struct { s3_acd1100_t protocol; bool ready; } s3_co2_driver_t;
void s3_co2_init(s3_co2_driver_t *d, uint32_t now);
void s3_co2_service(s3_co2_driver_t *d, environment_record_t *r, uint32_t now);
#endif
