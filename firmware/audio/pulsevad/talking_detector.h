#ifndef MOSAIC_TALKING_DETECTOR_H
#define MOSAIC_TALKING_DETECTOR_H
typedef enum {
    TALKING_NO_SPEECH, TALKING_PENDING, TALKING_CONFIRMED,
    TALKING_LOW_LEVEL, TALKING_CLIPPED, TALKING_TIMING_FAULT, TALKING_INVALID
} talking_event_t;
typedef struct {
    unsigned positive_blocks;
    unsigned weak_blocks;
    unsigned active;
} talking_detector_state_t;
float talking_head_probability(const float embedding[8]);
int talking_uses_own_head(void);
/* A vote is one of three overlapping contexts within ONE 500 ms block.
 * Start after >=2 votes in each of two successive valid blocks. Once active,
 * bridge one weak block; release on the second consecutive weak block.
 * Quality/timing faults reset immediately. This is event persistence, not
 * an increase in the model's speech probability or speaker identification.
 */
talking_event_t talking_detector_step(talking_detector_state_t *state, unsigned votes,
                                     float rms, unsigned clipped, int timing_fault);
const char *talking_event_name(talking_event_t event);
#endif
