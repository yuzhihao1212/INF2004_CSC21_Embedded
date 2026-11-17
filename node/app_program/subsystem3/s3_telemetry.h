#ifndef S3_TELEMETRY_H
#define S3_TELEMETRY_H
#include "environment.h"
/* Translate only environmental flags. PIR is posted separately as samples. */
uint8_t s3_environment_wire_flags(const environment_record_t *record);
#endif
