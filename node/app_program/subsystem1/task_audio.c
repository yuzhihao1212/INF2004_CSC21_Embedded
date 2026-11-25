/*
 *  task_audio.c
 *  Subsystem 1 -- the audio task (priority 13, core 0).
 *
 *  One loop per 500 ms window:
 *    1. wait for the DMA capture of 8000 ADC samples (drv_audio.c)
 *    2. apply the configured digital gain about the window's mean
 *    3. measure signal quality: RMS, clipping, minimum and maximum
 *    4. extract 20 Q8 features with integer-only DSP (audio_dsp.c)
 *    5. send the features to subsystem 2 by value (IF-13)
 *  The driver is already capturing the next window into its other buffer
 *  while steps 2 to 5 run.
 */

#include "../subsystem5/subsystem5.h"
#include "../subsystem2/subsystem2.h"
#include "subsystem1.h"
#include "drv_audio.h"
#include "audio_dsp.h"
#include "audio_signal_quality.h"

#define WINDOW_SAMPLES  8000    /* 500 ms at 16 kHz = AUDIO_DSP_WINDOW_SAMPLES */
#define WINDOW_US       500000  /* deadline, in audio_clock_us() counts: see the
                                   scale note in drv_audio.c */
#define UNITY_GAIN_X256 256     /* Q8.8 gain of 1.0: samples stay untouched */
#define ADC_MAX         4095    /* 12-bit ADC full scale */

void audio_task(INT stacd, void *exinf)
{
    (void)stacd; (void)exinf;
    audio_features_t msg = {0};
    mosaic_config_t config = MOSAIC_DEFAULT_CONFIG;

    audio_dsp_init();
    ER er = audio_capture_start();
    if (er < 0) {
        tm_printf((UB*)"audio init failed: %d\n", er);
        tk_exd_tsk(); return;
    }
    tm_printf((UB*)"audio: GP26 16kHz 500ms integer DSP\n");

    for (;;) {
        uint16_t *adc; audio_signal_quality_t q;

        /* Every pass uses up a sequence number, including a failed wait or
         * a rejected window: subsystem 2 counts each gap as dropped windows. */
        ++msg.sequence;
        er = audio_capture_wait(&adc, &msg.captured_us);
        if (er < 0) { tm_printf((UB*)"audio wait failed: %d\n", er); continue; }
        msg.capture_us = audio_capture_duration_us();

        /* IF-12: take the latest applied CONFIG; keep the last one if S5 is busy. */
        mosaic_config_t updated;
        if (s5_get_config(&updated) == E_OK) config = updated;

        /* Digital gain about the window mean, so the DC offset is not
         * amplified. The result is clamped to the ADC range. */
        if (config.audio_gain_x256 != UNITY_GAIN_X256) {
            uint32_t sum = 0;
            for (unsigned i = 0; i < WINDOW_SAMPLES; ++i) sum += adc[i];
            int32_t mean = (int32_t)(sum / WINDOW_SAMPLES);
            for (unsigned i = 0; i < WINDOW_SAMPLES; ++i) {
                int32_t v = mean + ((int32_t)adc[i] - mean) * config.audio_gain_x256 / UNITY_GAIN_X256;
                adc[i] = (uint16_t)(v < 0 ? 0 : v > ADC_MAX ? ADC_MAX : v);
            }
        }
        if (!audio_signal_quality(adc, WINDOW_SAMPLES, &q)) continue;

        uint64_t start = audio_clock_us();
        audio_dsp_process(adc, msg.features);
        uint64_t end = audio_clock_us();
        msg.dsp_us = (uint32_t)(end - start);
        msg.rms_q8 = q.ac_rms_q8; msg.clipped = q.clipped_samples;
        msg.adc_mean_q8 = q.mean_q8; msg.adc_min = q.minimum; msg.adc_max = q.maximum;
        /* Deadline check: the features were ready more than one window
         * after the capture finished. Subsystem 2 then reports UNKNOWN.
         * With the clock's present scale this cannot trip (drv_audio.c). */
        msg.timing_fault = end - msg.captured_us > WINDOW_US;
        msg.threshold_pct = config.audio_conf_threshold_pct;
        /* Full queue drops the new observation. S2 sees the sequence gap
         * and accounts for drops in order, avoiding races with old results. */
        (void)tk_snd_mbf(mbf_audio_features, &msg, sizeof msg, TMO_POL);
    }
}
