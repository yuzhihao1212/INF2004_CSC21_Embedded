#include "audio_stream.h"
#include <stdio.h>

int audio_stream_emit(const uint16_t *samples, uint32_t window,
                      uint64_t delivered_us, void (*write)(const char *, size_t)) {
    if (!samples || !write) return 0;
    uint32_t checksum = 0;
    for (unsigned i = 0; i < 8000; ++i) {
        if (samples[i] > 4095) return 0;
        checksum += samples[i];
    }
    char header[128];
    int n = snprintf(header, sizeof(header), "PCM_BEGIN,1,%lu,%llu,8000,16000,12000,%lu\n",
                     (unsigned long)window, (unsigned long long)delivered_us, (unsigned long)checksum);
    write(header, (size_t)n);
    unsigned char packed[384];
    for (unsigned offset = 0; offset < 8000; offset += 256) {
        unsigned end = offset + 256;
        if (end > 8000) end = 8000;
        unsigned used = 0;
        for (unsigned i = offset; i < end; i += 2) {
            unsigned a = samples[i], b = samples[i+1];
            packed[used++] = (unsigned char)a;
            packed[used++] = (unsigned char)((a >> 8) | ((b & 15) << 4));
            packed[used++] = (unsigned char)(b >> 4);
        }
        write((const char *)packed, used);
    }
    n = snprintf(header, sizeof(header), "\nPCM_END,%lu\n", (unsigned long)window);
    write(header, (size_t)n);
    return 1;
}
