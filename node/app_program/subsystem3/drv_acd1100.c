#include "drv_acd1100.h"
#include "drv_uart1.h"

void s3_co2_init(s3_co2_driver_t *d, uint32_t now)
{
    s3_acd1100_init(&d->protocol, now);
    d->ready = s3_uart1_init();
}

void s3_co2_service(s3_co2_driver_t *d, environment_record_t *r, uint32_t now)
{
    s3_acd1100_t *s = &d->protocol;
    if (!d->ready) {
        environment_apply_co2(r, SENSOR_RESOURCE_ERROR, 0, now);
        return;
    }
    s3_acd1100_tick(s, r, now);
    if (s->waiting) {
        for (unsigned i = 0; i < 9 && s->waiting; ++i) {
            int byte = s3_uart1_read();
            if (byte == -1) break;
            if (byte < 0) {
                s->waiting = false;
                environment_apply_co2(r, SENSOR_PROTOCOL_ERROR, 0, now);
                break;
            }
            s3_acd1100_byte(s, r, (uint8_t)byte, now);
        }
        return;
    }
    if (!s3_acd1100_due(s, now)) return;
    /* Mark even failed attempts, avoiding a tight retry loop on a noisy line. */
    (void)s3_acd1100_begin(s, now);
    unsigned drained;
    for (drained = 0; drained < 32; ++drained)
        if (s3_uart1_read() == -1) break;
    if (drained == 32 || !s3_uart1_send(s3_acd1100_read_command)) {
        s->waiting = false;
        environment_apply_co2(r, SENSOR_PROTOCOL_ERROR, 0, now);
    }
}
