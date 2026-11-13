#include <assert.h>
#include <stdio.h>
#include "audio_handoff.h"

int main(void) {
    mosaic_audio_handoff_t s = {0};
    mosaic_telemetry_t t = {0};
    mosaic_audio_window_t a = {.rms_x16=160, .audio_class=MOSAIC_AUDIO_BACKGROUND_NOISE,
                               .prob_pct={90,8,0,2}};
    mosaic_audio_window_t b = {.rms_x16=320, .audio_class=MOSAIC_AUDIO_TRANSIENT_NOISE,
                               .prob_pct={5,5,0,90}};
    mosaic_audio_take(&s, &t);
    assert(t.audio_window_count == 0 && t.audio_window_seq == 0);
    assert(mosaic_audio_publish(&s, &a, 100, 30));
    assert(mosaic_audio_publish(&s, &b, 90, 40));
    mosaic_audio_take(&s, &t);
    assert(t.audio_window_count == 2 && t.audio_window_seq == 2);
    assert(t.audio[0].rms_x16 == 160 && t.audio[1].rms_x16 == 320);
    assert(t.dsp_time_us == 100 && t.inference_time_us == 40);
    assert(mosaic_audio_publish(&s, &a, 110, 10));
    assert(mosaic_audio_publish(&s, &a, 50, 20));
    assert(mosaic_audio_publish(&s, &b, 40, 30));
    mosaic_audio_take(&s, &t);
    assert(t.audio_window_count == 2 && t.audio_window_seq == 5);
    assert(t.audio_overruns == 1 && t.dsp_time_us == 110);
    assert(mosaic_audio_publish(&s, &a, 1, 1));
    mosaic_audio_capture_dropped(&s, 2);
    assert(mosaic_audio_publish(&s, &b, 2, 2));
    mosaic_audio_take(&s, &t);
    assert(t.audio_window_count == 1 && t.audio_window_seq == 9);
    assert(t.audio_overruns == 4); /* Overflow + pending + two capture losses. */
    assert(t.audio[1].rms_x16 == 0);
    a.prob_pct[0] = 101;
    assert(!mosaic_audio_publish(&s, &a, 0, 0));
    assert(s.sequence == 9);
    a.prob_pct[0] = 90;
    s.sequence = UINT16_MAX;
    s.overruns = UINT16_MAX - 1;
    mosaic_audio_capture_dropped(&s, 2);
    assert(s.sequence == 1 && s.overruns == UINT16_MAX);

    /* Emit actual C wire bytes for the Python gateway check. */
    s = (mosaic_audio_handoff_t){0};
    assert(mosaic_audio_publish(&s, &a, 123, 20));
    assert(mosaic_audio_publish(&s, &b, 122, 21));
    mosaic_telemetry_packet_t packet = {0};
    mosaic_header_init(&packet.header, MOSAIC_MSG_TELEMETRY, 1,
                       sizeof packet.payload, 7, 1000);
    mosaic_audio_take(&s, &packet.payload);
    assert(fwrite(&packet, sizeof packet, 1, stdout) == 1);
    return 0;
}
