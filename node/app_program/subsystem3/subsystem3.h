/*
 *	subsystem3.h
 *	Subsystem 3 -- Environment sensors: DHT22, ACD1100 CO2 and PIR.
 *	Owner: Kendrick (kthgoat).  Student ID: 2500144.
 *
 *	One task, environment_task, owns GP2 (DHT22 by PIO and DMA), UART1
 *	(CO2) and GP16 (PIR), and posts validated readings to subsystem 5
 *	(IF-08, IF-09).  The template's consumer example is kept: IF-01 to
 *	IF-04 and tests S3-U01, INT-01 and INT-02 still use it.
 *
 *	Public interface of subsystem 3.  Other subsystems include it as
 *	"../subsystem3/subsystem3.h".
 */

#ifndef SUBSYSTEM3_H
#define SUBSYSTEM3_H

#include "../app.h"
#include <stdint.h>

#define S3_PRI_CONSUMER		16	/* priority band 16-17 (TEAM.md) */
#define S3_PRI_ENVIRONMENT       17
#define S3_BATCH_SIZE		5	/* report to subsystem 4 every N samples */

/* IF-01: send SAMPLE_MSG (subsystem2.h) here with tk_snd_mbx */
IMPORT ID	mbx_samples;

/* IF-04: statistics.  Read them ONLY while holding mtx_stats:
 *	tk_loc_mtx(mtx_stats, TMO_FEVR);  copy = app_stats;  tk_unl_mtx(mtx_stats);
 */
typedef struct {
	UW	received;	/* samples received so far */
	INT	min;
	INT	max;
	W	sum;
} APP_STATS;

IMPORT ID		mtx_stats;
IMPORT APP_STATS	app_stats;

/* Private to subsystem 3 */
IMPORT void	consumer_task(INT stacd, void *exinf);
IMPORT void environment_task(INT stacd, void *exinf);
/* Snapshot with an atomic load: zero after startup failure or task exit. */
IMPORT ID tid_environment;
/* Atomic snapshot of completed environment service iterations. */
IMPORT uint32_t s3_environment_progress(void);

#if APP_TEST
#include "environment_service.h"
typedef struct {
    environment_record_t record;
    s3_diagnostic_counts_t counts;
    uint32_t progress, s5_errors;
    bool co2_warmed, dht_active, dht_stopping;
} s3_diagnostic_snapshot_t;
/* Returns false when no snapshot is available or the existing mutex is busy. */
bool s3_diagnostic_read(s3_diagnostic_snapshot_t *out);
#endif

#endif /* SUBSYSTEM3_H */
