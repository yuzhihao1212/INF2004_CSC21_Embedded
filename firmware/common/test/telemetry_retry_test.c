#include <assert.h>
#include <string.h>
#include "telemetry_retry.h"

int main(void) {
    mosaic_retry_queue_t q = {0};
    mosaic_telemetry_packet_t packet = {0}, out;
    packet.header.seq = 42;
    packet.payload.co2_ppm = 750;
    assert(mosaic_retry_add(&q, &packet, 0));
    packet.payload.co2_ppm = 999; /* Queue owns a copy, not producer memory. */
    assert(!mosaic_retry_take(&q, 99, &out));
    assert(mosaic_retry_take(&q, 100, &out));
    assert(out.header.seq == 42 && out.payload.co2_ppm == 750);
    assert(!mosaic_retry_take(&q, 299, &out));
    assert(mosaic_retry_take(&q, 300, &out));
    assert(!mosaic_retry_take(&q, 301, &out)); /* Exactly two retry attempts. */
    assert(mosaic_retry_add(&q, &packet, 1000));
    assert(!mosaic_retry_take(&q, 1600, &out)); /* No stale burst after outage. */
    assert(q.expired == 1);
    memset(&q, 0, sizeof q);
    for (unsigned i = 0; i < MOSAIC_RETRY_SLOTS; ++i) {
        packet.header.seq = i;
        assert(mosaic_retry_add(&q, &packet, 2000));
    }
    assert(!mosaic_retry_add(&q, &packet, 2000));
    assert(q.overflow == 1);
    for (unsigned i = 0; i < MOSAIC_RETRY_SLOTS; ++i) {
        assert(mosaic_retry_take(&q, 2100, &out));
        assert(out.header.seq == i);
    }
    /* A delayed scheduler still spaces retries rather than sending both now. */
    assert(mosaic_retry_take(&q, 2400, &out));
    assert(!mosaic_retry_take(&q, 2600, &out));
    return 0;
}
