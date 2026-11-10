#ifndef MOSAIC_NODE_AUDIO_H
#define MOSAIC_NODE_AUDIO_H
#include <stdbool.h>
#include <stdint.h>
#include "mosaic_protocol.h"

/* One audio producer, task context only, after node startup. These calls copy
 * their inputs under a short lock and never perform networking. No pointer to
 * a feature/DMA buffer is retained. Use the agreed FOUR wire classes; generic
 * speech must not be relabelled as lecturer/student without a team decision. */
bool mosaic_node_audio_publish(const mosaic_audio_window_t *window,
                              uint32_t dsp_us, uint32_t inference_us);
/* Capture gaps advance sequence and drop earlier pending entries to keep a
 * two-window wire batch consecutive. Call once per actual gap, not per retry. */
void mosaic_node_audio_dropped(uint16_t windows);
/* Sample the current complete configuration before processing each window. */
mosaic_config_t mosaic_node_audio_config(void);
/* With MOSAIC_NODE_AUDIO_SOURCES, implement this task entry. The node creates
 * it on core 1; it must never return. Initialize ADC/DMA IRQ on that core.
 * Mark progress after each bounded iteration, even an invalid/empty window.
 * Do NOT mark it in the DMA ISR or a loop that bypasses stuck DSP work. */
void mosaic_node_audio_task(void *unused);
void mosaic_node_audio_progress(void);
#endif
