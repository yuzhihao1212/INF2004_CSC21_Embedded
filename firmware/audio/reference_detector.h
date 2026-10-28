#ifndef MOSAIC_REFERENCE_DETECTOR_H
#define MOSAIC_REFERENCE_DETECTOR_H
#include <stdint.h>
#include "pulsevad/talking_detector.h"
#define REFERENCE_CALIBRATION_MIN 20
#define REFERENCE_CALIBRATION_MAX 64
#define REFERENCE_INPUT_VALID 1u
typedef struct {
    uint64_t time_us; /* Common clock, NOT independent Pico boot times. */
    float rms;
    uint32_t speech_votes; /* Unchanged local ML votes: 0..3. */
    uint32_t valid; /* Set only for fresh, unclipped, no-overrun audio. */
} reference_reading_t;
typedef struct {
    float relative_margin; /* RMS fraction above learned upper envelope. */
    float absolute_margin; /* Additional local ADC RMS counts. */
    uint64_t max_skew_us, max_age_us;
} reference_config_t;
typedef struct {
    float reference_power[REFERENCE_CALIBRATION_MAX];
    float student_power[REFERENCE_CALIBRATION_MAX];
    unsigned count, ready;
    float power_scale, noise_intercept, residual_upper;
    uint64_t last_reference_us, last_student_us;
    unsigned have_previous;
    talking_detector_state_t speech;
    reference_config_t config;
} reference_detector_t;
typedef enum {
    REF_CALIBRATING, REF_BASELINE_READY, REF_NO_TALKING,
    REF_PENDING, REF_STUDENT_TALKING, REF_UNKNOWN
} reference_decision_t;
typedef struct {
    reference_decision_t decision;
    const char *reason;
    float expected_rms, threshold_rms;
    unsigned calibration_pairs, hold;
} reference_result_t;
void reference_detector_init(reference_detector_t *state);
/* Operator must keep students quiet during initial lecturer-only calibration.
 * Learns local power = scale * reference power + background intercept.
 * The margins are configurable prototype defaults, not validated accuracy.
 */
reference_result_t reference_detector_update(reference_detector_t *state,
    const reference_reading_t *reference, const reference_reading_t *student,
    uint64_t now_us);
const char *reference_decision_name(reference_decision_t decision);
#endif
