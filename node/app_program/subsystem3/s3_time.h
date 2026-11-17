#ifndef S3_TIME_H
#define S3_TIME_H
#include <stdbool.h>
#include <stdint.h>
/* All scheduled durations < 2^31 ms; caller services at least once per half wrap. */
static inline bool s3_elapsed(uint32_t now, uint32_t then, uint32_t duration)
{
    uint32_t age = now - then;
    return age < UINT32_C(0x80000000) && age >= duration;
}
#endif
