/*
 * Host-side protocol cross-check. Builds one datagram of each type with the
 * values pc/tests/test_protocol.py expects and prints each as "<name> <hex>".
 * The Python test compiles this file with the host C compiler and decodes the
 * output, so any layout drift between the C header and Python mirror fails CI.
 */
#include <stdio.h>
#include <string.h>
#include "mosaic_protocol.h"

static void dump(const char *name, const void *data, size_t len) {
    const unsigned char *bytes = data;
    printf("%s ", name);
    for (size_t i = 0; i < len; ++i) printf("%02x", bytes[i]);
    printf("\n");
}

int main(void) {
    mosaic_telemetry_packet_t t;
    memset(&t, 0, sizeof t);
    mosaic_header_init(&t.header, MOSAIC_MSG_TELEMETRY, 3, sizeof t.payload, 42, 123456);
    t.header.flags = MOSAIC_FLAG_FIRST_SINCE_BOOT;
    t.payload.temperature_x10 = -55;  /* Negative, to check the sign survives */
    t.payload.humidity_x10 = 612;
    t.payload.dsp_time_us = 81000;
    t.payload.inference_time_us = 950;
    t.payload.free_heap_bytes = 65536;
    t.payload.co2_ppm = 812;
    t.payload.config_version = 7;
    t.payload.audio_overruns = 2;
    t.payload.audio_window_seq = 301;
    t.payload.audio_window_count = 2;
    t.payload.audio[0] = (mosaic_audio_window_t){
        .rms_x16 = 200, .audio_class = MOSAIC_AUDIO_LECTURER_SPEECH, .prob_pct = {5, 80, 10, 5}};
    t.payload.audio[1] = (mosaic_audio_window_t){
        .rms_x16 = 0xFFFF, .audio_class = MOSAIC_AUDIO_UNKNOWN, .prob_pct = {30, 40, 20, 10}};
    t.payload.pir_active_pct = 35;
    t.payload.valid_flags = MOSAIC_VALID_TEMP_HUM | MOSAIC_VALID_CO2 | MOSAIC_VALID_PIR;
    t.payload.cpu_load_pct = 63;
    t.payload.wifi_rssi_dbm = -58;
    dump("telemetry", &t, sizeof t);

    mosaic_config_packet_t c;
    memset(&c, 0, sizeof c);
    mosaic_header_init(&c.header, MOSAIC_MSG_CONFIG, 3, sizeof c.payload, 9, 5000);  /* To node 3 */
    c.payload = (mosaic_config_t)MOSAIC_DEFAULT_CONFIG;
    c.payload.config_version = 7;
    c.payload.mode = MOSAIC_MODE_DISCUSSION;
    c.payload.audio_gain_x256 = 384;  /* 1.5 */
    if (mosaic_config_check(&c.payload, 0) != MOSAIC_ACK_OK) return 1;
    dump("config", &c, sizeof c);

    mosaic_config_ack_packet_t a;
    memset(&a, 0, sizeof a);
    mosaic_header_init(&a.header, MOSAIC_MSG_CONFIG_ACK, 3, sizeof a.payload, 43, 123500);
    a.payload.config_version = 7;
    a.payload.status = MOSAIC_ACK_OK;
    dump("config_ack", &a, sizeof a);

    mosaic_ping_packet_t p;
    memset(&p, 0, sizeof p);
    mosaic_header_init(&p.header, MOSAIC_MSG_PONG, 3, sizeof p.payload, 44, 123600);
    p.payload.pc_time_us = 1234567890123ULL;
    dump("pong", &p, sizeof p);

    /* Validation helpers must reject what the Python side rejects. */
    mosaic_config_t bad = MOSAIC_DEFAULT_CONFIG;
    bad.config_version = 1;
    bad.dht_interval_ms = 1000;  /* Below the DHT22 minimum */
    if (mosaic_config_check(&bad, 0) != MOSAIC_ACK_INVALID_VALUE) return 1;
    if (mosaic_config_check(&c.payload, 7) != MOSAIC_ACK_OK) return 1;  /* Retry */
    if (mosaic_config_check(&c.payload, 8) != MOSAIC_ACK_STALE_VERSION) return 1;
    if (mosaic_header_check(&t.header, sizeof t) != MOSAIC_ACK_OK) return 1;
    if (mosaic_header_check(&t.header, sizeof t - 1) != MOSAIC_ACK_INVALID_VALUE) return 1;
    return 0;
}
