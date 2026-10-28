#include "audio_raw_diagnostic.h"
#include <math.h>
#include <stdio.h>

int audio_raw_diagnostic_emit(const uint16_t *samples, uint32_t window,
                             uint64_t delivered_us, float pulse, float own,
                             void (*write)(const char *, size_t)) {
    int no_model = pulse == -1.0f && own == -1.0f;
    if (!samples || !write || !isfinite(pulse) || !isfinite(own) ||
        (!no_model && (pulse < 0 || pulse > 1 || own < 0 || own > 1))) return 0;
    uint32_t checksum = 0;
    for (unsigned i = 0; i < 8000; ++i) {
        if (samples[i] > 4095) return 0;
        checksum += samples[i];
    }
    char line[448];
    int n = snprintf(line, sizeof(line), "RAW_BEGIN,%lu,%llu,8000,16000,%.8f,%.8f\n",
                     (unsigned long)window, (unsigned long long)delivered_us, pulse, own);
    write(line, (size_t)n);
    static const char hex[] = "0123456789abcdef";
    for (unsigned offset = 0; offset < 8000; offset += 128) {
        n = snprintf(line, sizeof(line), "RAW_DATA,%lu,%u,", (unsigned long)window, offset);
        unsigned end = offset + 128;
        if (end > 8000) end = 8000;
        for (unsigned i = offset; i < end; ++i) {
            unsigned value = samples[i];
            line[n++] = hex[value >> 8];
            line[n++] = hex[(value >> 4) & 15];
            line[n++] = hex[value & 15];
        }
        line[n++] = '\n';
        write(line, (size_t)n);
    }
    n = snprintf(line, sizeof(line), "RAW_END,%lu,%lu\n", (unsigned long)window, (unsigned long)checksum);
    write(line, (size_t)n);
    return 1;
}
