#include "s5_protocol.h"
#include <string.h>

static void add_overruns(s5_audio_t *a, uint32_t n)
{
    uint32_t room = UINT16_MAX - a->overruns;
    a->overruns += (uint16_t)(n < room ? n : room);
}

void s5_init(s5_state_t *s, uint8_t node_id)
{
    const mosaic_config_t defaults = MOSAIC_DEFAULT_CONFIG;
    memset(s, 0, sizeof *s);
    s->node_id = node_id;
    s->config = defaults;
    s->first_telemetry = true;
}

s5_control_result_t s5_handle_control(s5_state_t *s, const uint8_t *bytes,
    size_t len, uint32_t now_ms, uint8_t *reply, size_t *reply_len)
{
    mosaic_header_t h;
    *reply_len = 0;
    if (!bytes || len < sizeof h || len > MOSAIC_MAX_DATAGRAM) return S5_IGNORED;
    memcpy(&h, bytes, sizeof h);
    if (mosaic_header_check(&h, len) != MOSAIC_ACK_OK || h.node_id != s->node_id)
        return S5_IGNORED;
    if (h.msg_type == MOSAIC_MSG_CONFIG) {
        mosaic_config_t c;
        mosaic_config_ack_packet_t ack = {0};
        memcpy(&c, bytes + sizeof h, sizeof c);
        mosaic_ack_status_t status = mosaic_config_check(&c, s->config.config_version);
        if (status == MOSAIC_ACK_OK) s->config = c;
        mosaic_header_init(&ack.header, MOSAIC_MSG_CONFIG_ACK, s->node_id,
                           sizeof ack.payload, 0, now_ms);
        ack.payload.config_version = c.config_version;
        ack.payload.status = (uint8_t)status;
        memcpy(reply, &ack, sizeof ack);
        *reply_len = sizeof ack;
        return status == MOSAIC_ACK_OK ? S5_CONFIG_APPLIED : S5_CONFIG_REJECTED;
    }
    if (h.msg_type == MOSAIC_MSG_PING) {
        mosaic_ping_packet_t pong = {0};
        mosaic_header_init(&pong.header, MOSAIC_MSG_PONG, s->node_id,
                           sizeof pong.payload, 0, now_ms);
        memcpy(&pong.payload, bytes + sizeof h, sizeof pong.payload);
        memcpy(reply, &pong, sizeof pong);
        *reply_len = sizeof pong;
        return S5_PONG;
    }
    return S5_IGNORED;
}

void s5_update_environment(s5_state_t *s, int16_t temperature_x10,
    uint16_t humidity_x10, uint16_t co2_ppm, uint8_t valid_bits, uint64_t now_ms)
{
    s->temperature_x10 = temperature_x10;
    s->humidity_x10 = humidity_x10;
    s->co2_ppm = co2_ppm;
    s->env_valid = valid_bits & (MOSAIC_VALID_TEMP_HUM | MOSAIC_VALID_CO2 |
                                MOSAIC_VALID_CO2_WARMUP);
    s->env_posted_ms = now_ms;
}

void s5_update_pir(s5_state_t *s, uint32_t samples, uint32_t active)
{
    if (active > samples) active = samples;
    uint32_t room = UINT32_MAX - s->pir_samples;
    s->pir_samples += samples < room ? samples : room;
    room = UINT32_MAX - s->pir_active;
    s->pir_active += active < room ? active : room;
}

bool s5_publish_audio(s5_state_t *s, const mosaic_audio_window_t *window,
                       uint32_t dsp_us, uint32_t inference_us)
{
    s5_audio_t *a = &s->audio;
    if (!window || window->reserved ||
        window->audio_class > MOSAIC_AUDIO_TRANSIENT_NOISE ||
        window->audio_class == MOSAIC_AUDIO_RESERVED || window->prob_pct[2] != 0)
        return false;
    for (unsigned i = 0; i < MOSAIC_AUDIO_CLASS_COUNT; ++i)
        if (window->prob_pct[i] > 100) return false;
    if (a->count == MOSAIC_AUDIO_WINDOWS_PER_REPORT) {
        a->windows[0] = a->windows[1];
        a->count--;
        add_overruns(a, 1);
    }
    a->windows[a->count++] = *window;
    a->sequence++; /* Deliberate uint16_t wrap, as in audio_handoff.h. */
    if (dsp_us > a->dsp_us) a->dsp_us = dsp_us;
    if (inference_us > a->inference_us) a->inference_us = inference_us;
    return true;
}

void s5_capture_dropped(s5_state_t *s, uint16_t windows)
{
    s5_audio_t *a = &s->audio;
    if (!windows) return;
    add_overruns(a, windows);
    add_overruns(a, a->count);
    a->sequence += windows;
    a->count = 0;
}

void s5_update_health(s5_state_t *s, int8_t rssi_dbm, uint8_t cpu_load_pct,
                       uint32_t free_heap_bytes)
{
    s->rssi_dbm = rssi_dbm;
    s->cpu_load_pct = cpu_load_pct > 100 ? 100 : cpu_load_pct;
    s->free_heap_bytes = free_heap_bytes;
}

void s5_build_telemetry(s5_state_t *s, uint64_t now_ms,
                        mosaic_telemetry_packet_t *packet)
{
    memset(packet, 0, sizeof *packet);
    mosaic_header_init(&packet->header, MOSAIC_MSG_TELEMETRY, s->node_id,
                       sizeof packet->payload, 0, (uint32_t)now_ms);
    if (s->first_telemetry) packet->header.flags = MOSAIC_FLAG_FIRST_SINCE_BOOT;
    mosaic_telemetry_t *t = &packet->payload;
    /* Keep the full boot clock so a hung sensor cannot reappear at the
     * 32-bit wire-clock wrap (~49.7 days). */
    if (now_ms - s->env_posted_ms <= S5_ENV_MAX_AGE_MS) {
        t->valid_flags = s->env_valid;
        if (s->env_valid & MOSAIC_VALID_TEMP_HUM) {
            t->temperature_x10 = s->temperature_x10;
            t->humidity_x10 = s->humidity_x10;
        }
        if (s->env_valid & MOSAIC_VALID_CO2) t->co2_ppm = s->co2_ppm;
    }
    if (s->pir_samples) {
        t->pir_active_pct = (uint8_t)(100ull * s->pir_active / s->pir_samples);
        t->valid_flags |= MOSAIC_VALID_PIR;
    }
    s->pir_samples = s->pir_active = 0;
    s5_audio_t *a = &s->audio;
    memcpy(t->audio, a->windows, a->count * sizeof a->windows[0]);
    t->audio_window_count = a->count;
    t->audio_window_seq = a->sequence;
    t->audio_overruns = a->overruns;
    t->dsp_time_us = a->dsp_us;
    t->inference_time_us = a->inference_us;
    a->count = 0;
    a->dsp_us = a->inference_us = 0;
    t->config_version = s->config.config_version;
    t->wifi_rssi_dbm = s->rssi_dbm;
    t->cpu_load_pct = s->cpu_load_pct;
    t->free_heap_bytes = s->free_heap_bytes;
}

void s5_stamp_seq(const s5_state_t *s, mosaic_header_t *header)
{
    header->seq = s->seq;
}

void s5_sent(s5_state_t *s, const mosaic_header_t *header, bool accepted,
             uint8_t audio_count)
{
    if (accepted) s->seq++;
    if (header->msg_type == MOSAIC_MSG_TELEMETRY) {
        if (accepted) s->first_telemetry = false;
        else add_overruns(&s->audio, audio_count);
    }
}
