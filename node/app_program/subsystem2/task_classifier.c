/*
 *  task_classifier.c
 *  Subsystem 2 -- the classifier task (priority 15, core 1).
 *
 *  For each feature window from subsystem 1 (IF-13):
 *    1. detect lost windows from the gap in the sequence number
 *    2. run the int8 network and the gates (audio_inference.c)
 *    3. report any lost windows to subsystem 5, then post this result (IF-10)
 *  Lost windows are always reported before the next result, so the PC sees
 *  losses and results in the order they happened. Every pass, including an
 *  idle one, tells subsystem 4's supervisor that this task is still running.
 */

#include "../subsystem5/subsystem5.h"
#include "subsystem2.h"
#include "audio_inference.h"
#include "../subsystem1/drv_audio.h"
#include "../subsystem4/s4_health.h"

#define WINDOW_US       500000  /* deadline, in audio_clock_us() counts: see the
                                   scale note in subsystem1/drv_audio.c */
#define FEATURE_COUNT   20
#define LAST_FEATURE    19      /* FEATURE_COUNT - 1: ends the console line */
#define LOG_EVERY       4       /* console line every 4th window = every 2 s */
#define IDLE_POLL_MS    250     /* wake at least this often to report progress */

void classifier_task(INT stacd, void *exinf)
{
    (void)stacd; (void)exinf;
    classifier_timing_state_t state = {0};  /* speech persistence across windows */
    uint32_t previous = 0, dropped = 0, logged = 0;

    for (;;) {
        audio_features_t in; mosaic_audio_window_t out;
        INT size = tk_rcv_mbf(mbf_audio_features, &in, IDLE_POLL_MS);
        if (size == E_TMOUT) {
            /* Idle classifier is healthy. The audio task has its own flag. */
            (void)s4_health_mark(S4_HEALTH_CLASSIFIER);
            continue;
        }
        if (size != sizeof in) { state = (classifier_timing_state_t){0}; continue; }

        /* A gap in the sequence means subsystem 1 lost windows: speech can
         * no longer be called consecutive, so persistence starts again. */
        uint32_t distance = in.sequence - previous;
        previous = in.sequence;
        if (distance != 1) {
            state = (classifier_timing_state_t){0};
            if (distance > 1) dropped += distance - 1;
        }

        uint64_t start = audio_clock_us();
        classifier_event_t event = classify_audio(&state, &in, start, &out);
        uint64_t end = audio_clock_us();
        /* Deadline: a result finished more than one window after its audio
         * was captured is reported as UNKNOWN, never as a late label. With
         * the clock's present scale this cannot trip (drv_audio.c). */
        if (end - in.captured_us > WINDOW_US) {
            out.audio_class = MOSAIC_AUDIO_UNKNOWN;
            state = (classifier_timing_state_t){0}; event = CLASSIFIER_TIMING_FAULT;
        }

        /* S2 is the sole audio poster, preserving loss/result ordering. If
         * the losses cannot be reported yet, this window is added to them
         * and reported later. */
        if (dropped) {
            uint16_t batch = dropped > 65535 ? 65535 : (uint16_t)dropped;
            if (s5_audio_dropped(batch) != E_OK) {
                ++dropped;
                (void)s4_health_mark(S4_HEALTH_CLASSIFIER);
                continue;
            }
            dropped -= batch;
            if (dropped) {
                ++dropped;
                (void)s4_health_mark(S4_HEALTH_CLASSIFIER);
                continue;
            }
        }
        if (s5_post_audio_window(&out, in.dsp_us, (uint32_t)(end - start)) != E_OK) {
            ++dropped; state = (classifier_timing_state_t){0};
        }

        /* Console evidence for the test logs: result, then the model inputs. */
        if (++logged % LOG_EVERY == 0) {
            tm_printf((UB*)"audio seq=%u class=%u p=%u/%u/%u event=%s dsp_us=%u ml_us=%u\n",
                in.sequence, out.audio_class, out.prob_pct[0], out.prob_pct[1], out.prob_pct[3],
                classifier_event_name(event), in.dsp_us, (uint32_t)(end - start));
            tm_printf((UB*)"audio input seq=%u min=%u max=%u mean_q8=%u rms_q8=%u clipped=%u threshold=%u capture_us=%u features_q8=",
                in.sequence, in.adc_min, in.adc_max, in.adc_mean_q8, in.rms_q8, in.clipped, in.threshold_pct, in.capture_us);
            for (unsigned i = 0; i < FEATURE_COUNT; ++i)
                tm_printf((UB*)"%d%s", in.features[i], i == LAST_FEATURE ? "\n" : ",");
        }
        (void)s4_health_mark(S4_HEALTH_CLASSIFIER);
    }
}
