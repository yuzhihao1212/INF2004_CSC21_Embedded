/*
 *	subsystem1.c
 *	Subsystem 1 -- LED heartbeat: creates its objects and starts its task.
 *
 *	APIs shown: tk_cre_cyc, tk_sta_cyc
 */

#include "subsystem1.h"

EXPORT ID	tid_led;	/* IF-05, see subsystem1.h */
EXPORT ID	cyc_led;

EXPORT ER subsystem1_init(void)
{
	T_CCYC	ccyc = {0};

	/* Cyclic handler: once started, the kernel calls led_cyclic_handler
	   every S1_TICK_MS.  Without TA_STA it is created stopped; it is
	   started in subsystem1_start(), once the task it wakes exists. */
	ccyc.cycatr = TA_HLNG;
	ccyc.cychdr = (FP)led_cyclic_handler;
	ccyc.cyctim = S1_TICK_MS;	/* period, ms */
	ccyc.cycphs = S1_TICK_MS;	/* delay before the first call, ms */
	cyc_led = tk_cre_cyc(&ccyc);
	return (cyc_led < E_OK) ? cyc_led : E_OK;
}

EXPORT ER subsystem1_start(void)
{
	tid_led = app_start_task(led_task, S1_PRI_LED, 0, "led_task");
	if (tid_led < E_OK) {
		return tid_led;
	}
	ER er=tk_sta_cyc(cyc_led);
	if (er<0) return er;
	/* A separate ID keeps S4's example LED suspension away from audio. */
	T_CTSK task={0};
	task.task=(FP)audio_task; task.itskpri=S1_PRI_AUDIO;
	task.stksz=4096; task.tskatr=TA_HLNG|TA_RNG3;
#if TK_SUPPORT_SMP
	task.tskatr|=TA_ASSPRC; task.assprc=TP_PRC1;
#endif
	ID audio=tk_cre_tsk(&task);
	return audio<0?audio:tk_sta_tsk(audio,0);
}
