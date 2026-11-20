#include "../subsystem5/subsystem5.h"
#include "environment_service.h"
#include "drv_pir.h"
#include "s3_telemetry.h"
#include "s3_time.h"

static void increment(uint32_t *n) { if (*n != UINT32_MAX) ++*n; }

void s3_service_init(s3_service_t *s, uint32_t now)
{
    const mosaic_config_t defaults = MOSAIC_DEFAULT_CONFIG;
    *s = (s3_service_t){.config = defaults, .boot_ms = now,
        .pir_ms = now - 100u, .config_ms = now - 250u, .post_ms = now - 100u};
    s->pir_ready = s3_pir_init() == E_OK;
    s3_co2_init(&s->co2, now);
    environment_apply_dht(&s->record, SENSOR_WARMING_UP, 0, 0, now);
    environment_apply_co2(&s->record, s->co2.ready ? SENSOR_WARMING_UP : SENSOR_RESOURCE_ERROR, 0, now);
    if (!s->pir_ready) s->record.pir_status = SENSOR_RESOURCE_ERROR;
}

void s3_service_step(s3_service_t *s, uint32_t now, bool pio_available)
{
    /* No sensor read waits for an edge or reply; buffers stay in this object. */
    if (!s->dht_initialized && pio_available) {
        s->dht_initialized = true;
        if (!s3_dht_init(&s->dht))
            environment_apply_dht(&s->record, SENSOR_RESOURCE_ERROR, 0, 0, now);
    }
    if (s3_elapsed(now, s->boot_ms, 2000)) s->powered = true;
    if (s->powered && !s->dht_initialized)
        environment_apply_dht(&s->record, SENSOR_RESOURCE_ERROR, 0, 0, now);
#if APP_TEST
    bool dht_was_active = s->dht.active;
    bool dht_was_stopping = s->dht.stopping;
#endif
    s3_dht_service(&s->dht, &s->record, now);
#if APP_TEST
    if (dht_was_active && !dht_was_stopping &&
        (s->dht.stopping || !s->dht.active) && s->dht.result == SENSOR_TIMEOUT)
        increment(&s->diag.dht_timeouts);
    if (dht_was_active && !s->dht.active) {
        if (s->record.dht_status == SENSOR_OK) {
            increment(&s->diag.dht_ok);
            if (s->diag.dht_failed) increment(&s->diag.dht_recoveries);
            s->diag.dht_failed = false;
        } else {
            increment(&s->diag.dht_fail);
            s->diag.dht_failed = true;
        }
    }
    bool co2_was_waiting = s->co2.protocol.waiting;
    bool co2_was_attempted = s->co2.protocol.attempted;
    uint32_t co2_last_attempt = s->co2.protocol.last_attempt_ms;
    bool co2_timeout_due = co2_was_waiting &&
        s3_elapsed(now, s->co2.protocol.request_ms, 1000);
#endif
    s->co2.protocol.interval_ms = s->config.co2_interval_ms;
    s3_co2_service(&s->co2, &s->record, now);
#if APP_TEST
    if (co2_timeout_due) increment(&s->diag.co2_timeouts);
    /* A new request can fail during drain/transmit, including in the same
     * iteration that an old request times out. Count both events. */
    bool co2_new_attempt = s->co2.protocol.attempted &&
        (!co2_was_attempted || s->co2.protocol.last_attempt_ms != co2_last_attempt);
    if (!s->co2.protocol.waiting &&
        ((co2_was_waiting && !co2_timeout_due) || co2_new_attempt)) {
        switch (s->record.co2_status) {
        case SENSOR_OK: increment(&s->diag.co2_ok); break;
        case SENSOR_CHECKSUM_ERROR: increment(&s->diag.co2_checksums); break;
        case SENSOR_PROTOCOL_ERROR: increment(&s->diag.co2_protocol_errors); break;
        default: break;
        }
    }
#endif
    if (s3_elapsed(now, s->pir_ms, 100)) {
        s->pir_ms = now; /* skip missed samples; never invent catch-up readings */
        if (s->pir_ready) {
            bool high = s3_pir_read() != 0;
            environment_apply_pir(&s->record, high, now);
#if APP_TEST
            increment(&s->diag.pir_valid_samples);
            if (high) increment(&s->diag.pir_motion_samples);
#endif
            if (!s->pir_samples) s->pir_batch_ms = now;
            if (s->pir_samples != UINT32_MAX) {
                ++s->pir_samples;
                if (high) ++s->pir_active;
            } else increment(&s->pir_dropped);
        }
    }
    environment_expire(&s->record, now);
    /* Give hardware service priority over up to three 10 ms S5 mutex waits.
     * A stuck DMA abort must not suppress other sensor reports indefinitely. */
    if (s->dht.active && !s->dht.stopping) return;
    if (s3_elapsed(now, s->config_ms, 250)) {
        mosaic_config_t config;
        s->config_ms = now;
        s->config_result = s5_get_config(&config);
        if (s->config_result == E_OK) {
            /* Version zero is S5's legitimate boot default, not a CONFIG
             * packet. Validate all fields using the wire checker nonetheless. */
            mosaic_config_t checked = config;
            if (!checked.config_version && !s->config.config_version) checked.config_version = 1;
            if (mosaic_config_check(&checked, s->config.config_version) == MOSAIC_ACK_OK)
                s->config = config;
            else increment(&s->bad_configs);
        } else increment(&s->s5_errors); /* retain last good config */
    }
    if (s3_elapsed(now, s->post_ms, 100)) {
        s->post_ms = now;
        s->environment_result = s5_post_environment(s->record.temperature_x10,
            s->record.humidity_x10, s->record.co2_ppm, s3_environment_wire_flags(&s->record));
        if (s->environment_result != E_OK) {
            increment(&s->s5_errors);
#if APP_TEST
            increment(&s->diag.s5_post_errors);
#endif
        }
        if (s->pir_samples) {
            if (s3_elapsed(now, s->pir_batch_ms, 2000)) {
                increment(&s->pir_dropped); /* stale batch, not current activity */
                s->pir_samples = s->pir_active = 0;
            } else {
                s->pir_result = s5_post_pir(s->pir_samples, s->pir_active);
                if (s->pir_result == E_OK) s->pir_samples = s->pir_active = 0;
                else {
                    increment(&s->s5_errors);
#if APP_TEST
                    increment(&s->diag.s5_post_errors);
#endif
                    /* E_TMOUT/E_OBJ occur before any copy in current S5.
                     * Other errors could follow a successful copy (unlock);
                     * discard that batch to avoid double-counting on retry. */
                    if (s->pir_result != E_TMOUT && s->pir_result != E_OBJ) {
                        increment(&s->pir_dropped);
                        s->pir_samples = s->pir_active = 0;
                    }
                }
            }
        }
    }
}

void s3_service_start_due(s3_service_t *s, uint32_t now)
{
    if (s->dht.ready && !s->dht.active && s->powered &&
        (!s->dht_attempted || s3_elapsed(now, s->dht_ms, s->config.dht_interval_ms))) {
        if (s3_dht_start(&s->dht, now)) {
#if APP_TEST
            increment(&s->diag.dht_captures);
#endif
            s->dht_attempted = true;
            s->dht_ms = now;
        }
    }
}
