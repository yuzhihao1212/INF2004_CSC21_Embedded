/* Shared pure-logic checks for the host runner and TEST=1 image.
 * Every case owns its state; none touches the running report task. */
#ifndef S5_CASES_H
#define S5_CASES_H
#include "../../../app_program/subsystem5/s5_protocol.h"
#include <string.h>

static mosaic_config_packet_t s5_test_config(uint16_t version)
{
    mosaic_config_packet_t p = {0};
    mosaic_header_init(&p.header, MOSAIC_MSG_CONFIG, 1, sizeof p.payload, 9, 10);
    p.payload = (mosaic_config_t)MOSAIC_DEFAULT_CONFIG;
    p.payload.config_version = version;
    return p;
}

static bool s5_test_case(unsigned id)
{
    s5_state_t s;
    s5_init(&s, 1);
    mosaic_config_packet_t c = s5_test_config(2);
    mosaic_config_ack_packet_t ack;
    mosaic_telemetry_packet_t t;
    uint8_t reply[sizeof(mosaic_ping_packet_t)];
    size_t len = 99;
    mosaic_audio_window_t w = { .rms_x16 = 160,
        .audio_class = MOSAIC_AUDIO_SPEECH, .prob_pct = {5, 90, 0, 5} };
    switch (id) {
    case 1: {
        const mosaic_config_t defaults = MOSAIC_DEFAULT_CONFIG;
        return memcmp(&s.config, &defaults, sizeof defaults) == 0 &&
               s.config.config_version == 0 && s.config.report_interval_ms == 1000;
    }
    case 2:
        c.payload.report_interval_ms = 2000;
        c.payload.dht_interval_ms = 3000;
        c.payload.co2_interval_ms = 4000;
        c.payload.audio_gain_x256 = 512;
        c.payload.mode = MOSAIC_MODE_DISCUSSION;
        c.payload.audio_conf_threshold_pct = 75;
        if (s5_handle_control(&s, (const uint8_t *)&c, sizeof c, 123, reply, &len)
            != S5_CONFIG_APPLIED || len != sizeof ack) return false;
        memcpy(&ack, reply, sizeof ack);
        return ack.payload.status == MOSAIC_ACK_OK && ack.payload.config_version == 2 &&
               ack.payload.reserved == 0 && ack.header.sender_time_ms == 123 &&
               mosaic_header_check(&ack.header, len) == MOSAIC_ACK_OK &&
               memcmp(&s.config, &c.payload, sizeof s.config) == 0;
    case 3: {
        mosaic_config_t before = s.config;
        c.payload.report_interval_ms = 50;
        if (s5_handle_control(&s, (const uint8_t *)&c, sizeof c, 1, reply, &len)
            != S5_CONFIG_REJECTED || len != sizeof ack) return false;
        memcpy(&ack, reply, sizeof ack);
        return ack.payload.status == MOSAIC_ACK_INVALID_VALUE &&
               ack.payload.config_version == 2 &&
               memcmp(&s.config, &before, sizeof before) == 0;
    }
    case 4:
        s.config.config_version = 3;
        if (s5_handle_control(&s, (const uint8_t *)&c, sizeof c, 1, reply, &len)
            != S5_CONFIG_REJECTED) return false;
        memcpy(&ack, reply, sizeof ack);
        if (ack.payload.status != MOSAIC_ACK_STALE_VERSION ||
            s.config.config_version != 3) return false;
        c.payload.config_version = 3;
        c.payload.report_interval_ms = 2500;
        if (s5_handle_control(&s, (const uint8_t *)&c, sizeof c, 2, reply, &len)
            != S5_CONFIG_APPLIED) return false;
        memcpy(&ack, reply, sizeof ack);
        return ack.payload.status == MOSAIC_ACK_OK && s.config.report_interval_ms == 2500;
    case 5: {
        uint8_t bytes[MOSAIC_MAX_DATAGRAM + 2] = {0};
        for (unsigned bad = 0; bad < 10; ++bad) {
            c = s5_test_config(1);
            size_t n = sizeof c;
            switch (bad) {
            case 0: c.header.node_id = 2; break;
            case 1: c.header.magic = 0; break;
            case 2: n--; break;
            case 3: n = sizeof(mosaic_header_t) - 1; break;
            case 4: n = MOSAIC_MAX_DATAGRAM + 1; break;
            case 5: c.header.version++; break;
            case 6: c.header.payload_len--; break;
            case 7: c.header.msg_type = 99; break;
            case 8: n = 0; break;
            case 9: c.header.msg_type = MOSAIC_MSG_CONFIG_ACK;
                    c.header.payload_len = sizeof(mosaic_config_ack_t);
                    n = sizeof(mosaic_config_ack_packet_t); break;
            }
            /* Deliberately unaligned input and output. */
            memcpy(bytes + 1, &c, sizeof c);
            uint8_t out[sizeof(mosaic_ping_packet_t) + 1];
            s5_state_t before = s;
            if (s5_handle_control(&s, bytes + 1, n, 0, out + 1, &len) != S5_IGNORED ||
                len != 0 || memcmp(&s, &before, sizeof s) != 0) return false;
        }
        c = s5_test_config(1);
        memcpy(bytes + 1, &c, sizeof c);
        if (s5_handle_control(&s, bytes + 1, sizeof c, 0, reply, &len)
            != S5_CONFIG_APPLIED) return false;
        return len == sizeof ack;
    }
    case 6: {
        mosaic_ping_packet_t ping = {0}, pong;
        mosaic_header_init(&ping.header, MOSAIC_MSG_PING, 1, sizeof ping.payload, 5, 10);
        ping.payload.pc_time_us = UINT64_C(0x123456789abcdef0);
        if (s5_handle_control(&s, (const uint8_t *)&ping, sizeof ping, 456, reply, &len)
            != S5_PONG || len != sizeof pong) return false;
        memcpy(&pong, reply, sizeof pong);
        return pong.header.msg_type == MOSAIC_MSG_PONG &&
               pong.header.sender_time_ms == 456 &&
               pong.payload.pc_time_us == ping.payload.pc_time_us;
    }
    case 7:
        s5_build_telemetry(&s, 1, &t);
        s5_stamp_seq(&s, &t.header);
        if (!(t.header.flags & MOSAIC_FLAG_FIRST_SINCE_BOOT) || t.header.seq != 0)
            return false;
        s5_sent(&s, &t.header, false, 0);
        s5_build_telemetry(&s, 2, &t);
        s5_stamp_seq(&s, &t.header);
        if (!(t.header.flags & MOSAIC_FLAG_FIRST_SINCE_BOOT) || t.header.seq != 0)
            return false;
        s5_sent(&s, &t.header, true, 0);
        /* ACK shares the counter but must not change the telemetry flag. */
        ack.header.msg_type = MOSAIC_MSG_CONFIG_ACK;
        s5_stamp_seq(&s, &ack.header);
        if (ack.header.seq != 1) return false;
        s5_sent(&s, &ack.header, true, 0);
        s5_build_telemetry(&s, 3, &t);
        s5_stamp_seq(&s, &t.header);
        return t.header.flags == 0 && t.header.seq == 2;
    case 8:
        s5_update_pir(&s, 4, 1);
        s5_update_pir(&s, 6, 2);
        s5_build_telemetry(&s, 0, &t);
        if (t.payload.pir_active_pct != 30 || !(t.payload.valid_flags & MOSAIC_VALID_PIR))
            return false;
        s5_build_telemetry(&s, 1, &t);
        return t.payload.pir_active_pct == 0 && !(t.payload.valid_flags & MOSAIC_VALID_PIR);
    case 9:
        s5_update_environment(&s, 251, 657, 850,
            MOSAIC_VALID_TEMP_HUM | MOSAIC_VALID_CO2 | MOSAIC_VALID_CO2_WARMUP, 100);
        s5_build_telemetry(&s, 6100, &t);
        if (t.payload.temperature_x10 != 251 || t.payload.humidity_x10 != 657 ||
            t.payload.co2_ppm != 850 || t.payload.valid_flags != 7) return false;
        s5_build_telemetry(&s, 6101, &t);
        if (t.payload.valid_flags || t.payload.temperature_x10 ||
            t.payload.humidity_x10 || t.payload.co2_ppm) return false;
        s5_update_environment(&s, 250, 600, 900, 3, UINT32_MAX - 100u);
        s5_build_telemetry(&s, (uint64_t)UINT32_MAX + 101u, &t);
        if (t.payload.valid_flags != 3 || t.payload.co2_ppm != 900) return false;
        s5_build_telemetry(&s, (uint64_t)UINT32_MAX * 2u + 100u, &t);
        return t.payload.valid_flags == 0 && t.payload.co2_ppm == 0;
    case 10:
        for (unsigned i = 1; i <= 3; ++i) {
            w.rms_x16 = (uint16_t)(i * 160);
            if (!s5_publish_audio(&s, &w, i * 10, 40 - i)) return false;
        }
        w.audio_class = MOSAIC_AUDIO_RESERVED;
        if (s5_publish_audio(&s, &w, 999, 999)) return false;
        w.audio_class = MOSAIC_AUDIO_SPEECH;
        w.prob_pct[2] = 1;
        if (s5_publish_audio(&s, &w, 999, 999)) return false;
        s5_build_telemetry(&s, 0, &t);
        if (t.payload.audio_window_count != 2 || t.payload.audio_window_seq != 3 ||
            t.payload.audio_overruns != 1 || t.payload.audio[0].rms_x16 != 320 ||
            t.payload.audio[1].rms_x16 != 480 || t.payload.dsp_time_us != 30 ||
            t.payload.inference_time_us != 39) return false;
        s5_build_telemetry(&s, 1, &t);
        return t.payload.audio_window_count == 0 && t.payload.dsp_time_us == 0 &&
               t.payload.inference_time_us == 0 && t.payload.audio[0].rms_x16 == 0;
    case 11:
        if (!s5_publish_audio(&s, &w, 1, 2) || !s5_publish_audio(&s, &w, 2, 1))
            return false;
        s5_build_telemetry(&s, 0, &t);
        s5_stamp_seq(&s, &t.header);
        s5_sent(&s, &t.header, false, t.payload.audio_window_count);
        s5_build_telemetry(&s, 1, &t);
        return t.payload.audio_overruns == 2 && t.payload.audio_window_count == 0 &&
               s.seq == 0 && (t.header.flags & MOSAIC_FLAG_FIRST_SINCE_BOOT);
    default: return false;
    }
}
#endif
