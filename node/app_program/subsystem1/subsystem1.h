/*
 *	subsystem1.h
 *	Subsystem 1 -- Audio capture and fixed-point DSP.
 *	Owner: Moe (mmmmm0e).  Student ID: <student ID>.
 *
 *	Samples the microphone on GP26/ADC0 at 16 kHz by DMA and turns each
 *	500 ms window into 20 Q8 features for subsystem 2 (IF-13).  The
 *	template's LED heartbeat example is kept: IF-05 and tests S1-U01 and
 *	S1-U02 still use it.
 *
 *	This header is subsystem 1's PUBLIC interface: only what other
 *	subsystems are allowed to use.  Everything else stays LOCAL in the .c
 *	files.  Other subsystems include it as "../subsystem1/subsystem1.h".
 */

#ifndef SUBSYSTEM1_H
#define SUBSYSTEM1_H

#include "../app.h"
#include "audio_features.h"	/* IF-13 data format, sent to subsystem 2 */

#define S1_PRI_LED	12		/* priority band 12-13 (TEAM.md) */
#define S1_PRI_AUDIO	13		/* audio_task, pinned to core 0 */
#define S1_AUDIO_STACK_SIZE 4096	/* bytes, as claimed in TEAM.md */
#define S1_LED_PIN	19		/* GP19: LED + 330R resistor to GND */
#define S1_TICK_MS	250		/* LED toggles every tick */

/* IF-05: the LED task's ID, so subsystem 4 may pause/resume it */
IMPORT ID	tid_led;

/* Private to subsystem 1, shared between its own .c files */
IMPORT ID	cyc_led;
IMPORT void	led_task(INT stacd, void *exinf);
IMPORT void	led_cyclic_handler(void *exinf);
IMPORT void	audio_task(INT stacd, void *exinf);

#endif /* SUBSYSTEM1_H */
