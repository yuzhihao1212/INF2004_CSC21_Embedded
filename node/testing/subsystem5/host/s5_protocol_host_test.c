/* stdout is exactly one 64-byte TELEMETRY followed by one 20-byte ACK. */
#include "s5_cases.h"
#include <assert.h>
#include <stdio.h>

static void test_edges(void)
{
    s5_state_t s;
    mosaic_telemetry_packet_t t;
    mosaic_audio_window_t w = {.rms_x16 = 10, .audio_class = MOSAIC_AUDIO_SPEECH,
                               .prob_pct = {5, 90, 0, 5}};
    s5_init(&s, 1);
    assert(!s5_publish_audio(&s, NULL, 0, 0));
    w.reserved = 1;
    assert(!s5_publish_audio(&s, &w, 0, 0));
    w.reserved = 0;
    w.audio_class = 5;
    assert(!s5_publish_audio(&s, &w, 0, 0));
    w.audio_class = MOSAIC_AUDIO_SPEECH;
    w.prob_pct[0] = 101;
    assert(!s5_publish_audio(&s, &w, 0, 0));
    w.prob_pct[0] = 5;
    assert(s5_publish_audio(&s, &w, 123, 21));
    s5_capture_dropped(&s, 0);
    assert(s.audio.count == 1 && s.audio.sequence == 1);
    s5_capture_dropped(&s, 2);
    assert(s.audio.count == 0 && s.audio.sequence == 3 && s.audio.overruns == 3);
    assert(s5_publish_audio(&s, &w, 2, 1));
    s5_build_telemetry(&s, 1, &t);
    assert(t.payload.audio_window_count == 1 && t.payload.audio_window_seq == 4);
    assert(t.payload.dsp_time_us == 123 && t.payload.inference_time_us == 21);
    s.audio.overruns = UINT16_MAX - 1;
    s5_capture_dropped(&s, UINT16_MAX);
    assert(s.audio.overruns == UINT16_MAX);
    s.audio.sequence = UINT16_MAX;
    assert(s5_publish_audio(&s, &w, 0, 0));
    assert(s.audio.sequence == 0);
    s5_update_pir(&s, UINT32_MAX, UINT32_MAX);
    s5_update_pir(&s, 10, 10);
    assert(s.pir_samples == UINT32_MAX && s.pir_active == UINT32_MAX);
    s5_build_telemetry(&s, 2, &t);
    assert(t.payload.pir_active_pct == 100);
    s5_update_pir(&s, 1, UINT32_MAX);
    s5_build_telemetry(&s, 3, &t);
    assert(t.payload.pir_active_pct == 100);
    s5_update_environment(&s, 999, 999, 999, 0xff, 0);
    s5_build_telemetry(&s, 0, &t);
    assert(t.payload.valid_flags == 7); /* A poster cannot forge PIR validity. */
    s5_update_environment(&s, 999, 999, 999, 0, 0);
    s5_build_telemetry(&s, 0, &t);
    assert(!t.payload.valid_flags && !t.payload.temperature_x10 &&
           !t.payload.humidity_x10 && !t.payload.co2_ppm);
    s.seq = UINT32_MAX;
    mosaic_header_t h = {.msg_type = MOSAIC_MSG_PONG};
    s5_stamp_seq(&s, &h);
    assert(h.seq == UINT32_MAX);
    s5_sent(&s, &h, false, 0);
    assert(s.seq == UINT32_MAX && s.first_telemetry);
    s5_sent(&s, &h, true, 0);
    assert(s.seq == 0 && s.first_telemetry);
    s5_update_health(&s, -65, 255, 123456);
    s5_build_telemetry(&s, 0, &t);
    assert(t.payload.cpu_load_pct == 100 && t.payload.wifi_rssi_dbm == -65 &&
           t.payload.free_heap_bytes == 123456);
}

int main(void)
{
    for (unsigned id = 1; id <= 11; ++id) assert(s5_test_case(id));
    test_edges();
    s5_state_t s;
    s5_init(&s, 1);
    mosaic_config_packet_t c = s5_test_config(7);
    uint8_t reply[sizeof(mosaic_ping_packet_t)];
    size_t len;
    assert(s5_handle_control(&s, (const uint8_t *)&c, sizeof c, 42, reply, &len)
           == S5_CONFIG_APPLIED);
    mosaic_audio_window_t w = {.rms_x16 = 160, .audio_class = MOSAIC_AUDIO_SPEECH,
                              .prob_pct = {5, 90, 0, 5}};
    s5_update_environment(&s, 251, 657, 850, MOSAIC_VALID_TEMP_HUM | MOSAIC_VALID_CO2, 100);
    s5_update_pir(&s, 10, 3);
    s5_update_health(&s, -65, 42, 123456);
    assert(s5_publish_audio(&s, &w, 123, 21));
    w.rms_x16 = 320;
    w.audio_class = MOSAIC_AUDIO_TRANSIENT_NOISE;
    w.prob_pct[1] = 5;
    w.prob_pct[3] = 90;
    assert(s5_publish_audio(&s, &w, 100, 19));
    mosaic_telemetry_packet_t t;
    s5_build_telemetry(&s, 1000, &t);
    s5_stamp_seq(&s, &t.header);
    s5_sent(&s, &t.header, true, t.payload.audio_window_count);
    mosaic_header_t h;
    memcpy(&h, reply, sizeof h);
    s5_stamp_seq(&s, &h);
    memcpy(reply, &h, sizeof h);
    s5_sent(&s, &h, true, 0);
    assert(fwrite(&t, 1, sizeof t, stdout) == sizeof t);
    assert(fwrite(reply, 1, len, stdout) == len);
    return 0;
}
