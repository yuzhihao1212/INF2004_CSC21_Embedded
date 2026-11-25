/*
 *	subsystem2.h
 *	Subsystem 2 -- int8 audio classifier.
 *	Owner: Darius (Dkkan-dev).  Student ID: 2501046.
 *
 *	Receives each window's 20 Q8 features from subsystem 1 (IF-13), runs
 *	the integer-only 20-16-3 network on core 1 and posts the classified
 *	window to subsystem 5 (IF-10).  The template's producer example is
 *	kept: IF-01, IF-02 and tests S2-U01, S2-U02 and INT-01 still use it.
 *
 *	Public interface of subsystem 2.  Other subsystems include it as
 *	"../subsystem2/subsystem2.h".
 */

#ifndef SUBSYSTEM2_H
#define SUBSYSTEM2_H

#include "../app.h"
#include "../subsystem1/audio_features.h"

/* IF-13: subsystem 1 sends one audio_features_t per 500 ms window here,
   by value and with TMO_POL.  The buffer holds two windows. */
IMPORT ID	mbf_audio_features;
#define S2_FEATURE_QUEUE_DEPTH	2

#define S2_PRI_PRODUCER		14	/* priority band 14-15 (TEAM.md) */
#define S2_PRI_CLASSIFIER	15	/* classifier_task, pinned to core 1 */
#define S2_CLASSIFIER_STACK_SIZE 4096	/* bytes, as claimed in TEAM.md */
#define S2_PERIOD_MS		300	/* one sample every 300 ms */

/* ---------------------------------------------------------------------
 *  IF-01 data format: one sample, sent to subsystem 3's mailbox.
 *  A mailbox message MUST start with a T_MSG header: the kernel links
 *  messages together through it, so the data itself is never copied.
 * --------------------------------------------------------------------- */
typedef struct {
	T_MSG	hdr;		/* used by the kernel, do not touch */
	UW	seq;		/* sample sequence number */
	UW	time_ms;	/* system time when the sample was taken */
	INT	value;		/* the "measurement", 0..100 */
	INT	prc;		/* processor (core) that produced it: 1 or 2 */
} SAMPLE_MSG;

#define S2_POOL_COUNT	4	/* at most 4 samples in flight */

/* IF-02: the receiver of a sample gives its memory block back to
   mpf_samples (tk_rel_mpf) and then a slot back to sem_slots
   (tk_sig_sem, count 1).  Nothing else may use these two objects. */
IMPORT ID	sem_slots;
IMPORT ID	mpf_samples;

/* Private to subsystem 2 */
IMPORT void	producer_task(INT stacd, void *exinf);
IMPORT void	classifier_task(INT stacd, void *exinf);
IMPORT INT	s2_make_value(UW seq);

#endif /* SUBSYSTEM2_H */
