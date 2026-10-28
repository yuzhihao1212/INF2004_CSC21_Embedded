#ifndef MOSAIC_CLASSIFIER_TIMING_H
#define MOSAIC_CLASSIFIER_TIMING_H
#include <stdint.h>

typedef struct {
    uint64_t last_window_us;
    unsigned have_previous, positive_windows, weak_windows, active;
} classifier_timing_state_t;

typedef enum {
    CLASSIFIER_NO_SPEECH, CLASSIFIER_PENDING, CLASSIFIER_TALKING,
    CLASSIFIER_TRANSIENT, CLASSIFIER_LOW_LEVEL, CLASSIFIER_CLIPPED,
    CLASSIFIER_TIMING_FAULT, CLASSIFIER_INVALID
} classifier_event_t;

/* One observation per 500 ms window; classes: background=0,speech=1,transient=2.
 * Probabilities sum to 32768. This is persistence, not source identification.
 * Two consecutive speech-winning windows with P(speech)>=0.5 start an event.
 * One weak window is held; two release it. Transient winners veto immediately.
 * Gaps, clipping, low signal, invalid input and timing faults clear persistence.
 */
classifier_event_t classifier_timing_step(classifier_timing_state_t *state,
    unsigned predicted_class, const uint16_t probabilities_q15[3],
    uint32_t rms_q8, unsigned clipped_samples, int timing_fault, uint64_t window_us);
const char *classifier_event_name(classifier_event_t event);
#endif
