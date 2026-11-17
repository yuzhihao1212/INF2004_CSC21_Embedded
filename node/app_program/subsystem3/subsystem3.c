/*
 *	subsystem3.c
 *	Subsystem 3 -- Consumer: creates its objects and starts its task.
 *
 *	APIs shown: tk_cre_mbx, tk_cre_mtx
 */

#include "subsystem3.h"

EXPORT ID		mbx_samples;	/* IF-01 */
EXPORT ID		mtx_stats;	/* IF-04 */
EXPORT APP_STATS	app_stats;
EXPORT ID tid_environment;
/* Startup is called by the initial task, not concurrently by multiple tasks.
 * Keep dormant IDs after a failed start so a retry never creates duplicates. */
LOCAL ID tid_consumer;
LOCAL ID environment_object;
LOCAL BOOL consumer_started;
LOCAL BOOL environment_started;

EXPORT ER subsystem3_init(void)
{
	T_CMBX	cmbx = {0};
	T_CMTX	cmtx = {0};

	/* Mailbox: passes a POINTER to a message (zero copy).  The message
	   memory must stay valid until the receiver is done with it, which
	   is why subsystem 2 takes it from its memory pool. */
	cmbx.mbxatr = TA_TFIFO | TA_MFIFO;	/* FIFO waiters, FIFO messages */
	mbx_samples = tk_cre_mbx(&cmbx);
	if (mbx_samples < E_OK) {
		return mbx_samples;
	}

	/* Mutex: only one task at a time may touch app_stats.  TA_INHERIT
	   (priority inheritance) avoids priority inversion: a low-priority
	   holder is temporarily raised to the waiter's priority. */
	cmtx.mtxatr = TA_INHERIT;
	mtx_stats = tk_cre_mtx(&cmtx);
	if (mtx_stats < E_OK) {
		tk_del_mbx(mbx_samples);
		mbx_samples = 0;
	}
	return (mtx_stats < E_OK) ? mtx_stats : E_OK;
}

EXPORT ER subsystem3_start(void)
{
	if (mbx_samples <= 0 || mtx_stats <= 0) return E_OBJ;
	/* A task that has exited may still own hardware. Never restart it or
	 * erase/recreate its static DMA buffer; require a node reset instead. */
	T_RTSK state;
	ER er;
	if (environment_started) {
		er = tk_ref_tsk(environment_object, &state);
		if (er != E_OK) return er;
		if (state.tskstat == TTS_DMT) return E_OBJ;
	}
	if (consumer_started) {
		er = tk_ref_tsk(tid_consumer, &state);
		if (er != E_OK) return er;
		if (state.tskstat == TTS_DMT) return E_OBJ;
	}
	/* Use local creation rather than app_start_task: the shared helper
	 * returns an ID even when tk_sta_tsk fails. */
	T_CTSK task = {0};
	task.tskatr = TA_HLNG | TA_RNG3;
	task.stksz = TASK_STACK_SIZE;
#if TK_SUPPORT_SMP
	task.tskatr |= TA_ASSPRC;
	task.assprc = TP_PRC1;
#endif
	if (!consumer_started) {
		if (tid_consumer <= 0) {
			task.task = (FP)consumer_task;
			task.itskpri = S3_PRI_CONSUMER;
			ID id = tk_cre_tsk(&task);
			if (id <= 0) return id < 0 ? id : E_OBJ;
			tid_consumer = id;
		}
		er = tk_sta_tsk(tid_consumer, 0);
		if (er != E_OK) return er;
		consumer_started = 1;
	}
	if (!environment_started) {
		if (environment_object <= 0) {
			task.task = (FP)environment_task;
			task.itskpri = S3_PRI_ENVIRONMENT;
			ID id = tk_cre_tsk(&task);
			if (id <= 0) return id < 0 ? id : E_OBJ;
			environment_object = id;
		}
		/* Publish before start: an immediately exiting task can clear it
		 * without being overwritten by this caller afterwards. */
		__atomic_store_n(&tid_environment, environment_object, __ATOMIC_RELEASE);
		er = tk_sta_tsk(environment_object, 0);
		if (er != E_OK) {
			__atomic_store_n(&tid_environment, 0, __ATOMIC_RELEASE);
			return er;
		}
		environment_started = 1;
	}
	return E_OK;
}
