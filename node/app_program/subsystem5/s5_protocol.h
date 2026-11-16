/* Pure protocol state; independent of the kernel and of the live instance. */
#ifndef S5_PROTOCOL_H
#define S5_PROTOCOL_H
#include <stdint.h>
#include <stdbool.h>
#include "../../../firmware/common/include/mosaic_protocol.h"
#define S5_ENV_MAX_AGE_MS 6000u

typedef struct {
    mosaic_audio_window_t windows[MOSAIC_AUDIO_WINDOWS_PER_REPORT];
    uint16_t sequence, overruns;
    uint8_t count;
    uint32_t dsp_us, inference_us;
} s5_audio_t;
typedef struct {
    uint8_t node_id;
    mosaic_config_t config;
    uint32_t seq;
    bool first_telemetry;
    int16_t temperature_x10;
    uint16_t humidity_x10, co2_ppm;
    uint8_t env_valid;
    uint64_t env_posted_ms;
    uint32_t pir_samples, pir_active;
    s5_audio_t audio;
    int8_t rssi_dbm;
    uint8_t cpu_load_pct;
    uint32_t free_heap_bytes;
} s5_state_t;
typedef enum {
    S5_IGNORED, S5_CONFIG_APPLIED, S5_CONFIG_REJECTED, S5_PONG
} s5_control_result_t;

void s5_init(s5_state_t *s, uint8_t node_id);
/* reply needs sizeof(mosaic_ping_packet_t) bytes. reply_len is always set,
 * including zero for ignored input. Raw buffers may be unaligned. */
s5_control_result_t s5_handle_control(s5_state_t *s, const uint8_t *bytes,
    size_t len, uint32_t now_ms, uint8_t *reply, size_t *reply_len);
void s5_build_telemetry(s5_state_t *s, uint64_t now_ms,
                        mosaic_telemetry_packet_t *packet);
void s5_stamp_seq(const s5_state_t *s, mosaic_header_t *header);
void s5_sent(s5_state_t *s, const mosaic_header_t *header, bool accepted,
             uint8_t audio_count);
void s5_update_environment(s5_state_t *s, int16_t temperature_x10,
    uint16_t humidity_x10, uint16_t co2_ppm, uint8_t valid_bits, uint64_t now_ms);
void s5_update_pir(s5_state_t *s, uint32_t samples, uint32_t active);
bool s5_publish_audio(s5_state_t *s, const mosaic_audio_window_t *window,
                       uint32_t dsp_us, uint32_t inference_us);
void s5_capture_dropped(s5_state_t *s, uint16_t windows);
void s5_update_health(s5_state_t *s, int8_t rssi_dbm, uint8_t cpu_load_pct,
                       uint32_t free_heap_bytes);
#endif
