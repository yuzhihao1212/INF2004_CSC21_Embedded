/*
 *	subsystem4.h
 *	Subsystem 4 -- Networking and node health.
 *	Owner: Arif (arifkareem).  Student ID: 2500768.
 *
 *	The MQTT handoff is in s4_network.h (called only from the kernel's
 *	cyw43_utk_task).  The progress supervisor, s4_health_task, and the
 *	flags the other tasks set for it are in s4_health.h; the watchdog it
 *	can feed is in drv_watchdog.h and is off by default.  This header
 *	keeps the template's monitor example: IF-03 to IF-05 and tests
 *	S4-U01, S4-U02 and INT-02 still use it.
 *
 *	Public interface of subsystem 4.  Other subsystems include it as
 *	"../subsystem4/subsystem4.h".
 */

#ifndef SUBSYSTEM4_H
#define SUBSYSTEM4_H

#include "../app.h"

#define S4_PRI_MONITOR		18	/* priority band 18-19 (TEAM.md) */
#define S4_PRI_HEALTH		19
#define S4_ALARM_MS		2000	/* report anyway if nothing for 2 s */
#define S4_LED_TOGGLE_REPORTS	6	/* pause/resume the LED every N reports */

/* IF-03: send one text line (at most S4_SUMMARY_MAX bytes, no '\0'
   needed) to mbf_summary, then set FLG_BATCH in flg_events. */
#define S4_SUMMARY_MAX		48
#define FLG_BATCH		0x0002	/* set by subsystem 3 */
#define FLG_ALARM		0x0001	/* private: set by our alarm handler */

IMPORT ID	mbf_summary;
IMPORT ID	flg_events;

/* Private to subsystem 4 */
IMPORT ID	alm_monitor;
IMPORT UW	s4_lines_received;	/* for the tests */
IMPORT void	monitor_task(INT stacd, void *exinf);
IMPORT void	monitor_alarm_handler(void *exinf);

#endif /* SUBSYSTEM4_H */
