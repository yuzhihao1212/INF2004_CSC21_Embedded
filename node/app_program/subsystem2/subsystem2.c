/*
 *	subsystem2.c
 *	Subsystem 2 -- Producer: creates its objects and starts its task.
 *
 *	APIs shown: tk_cre_sem, tk_cre_mpf
 */

#include "subsystem2.h"

EXPORT ID	sem_slots;	/* IF-02, see subsystem2.h */
EXPORT ID	mpf_samples;
EXPORT ID mbf_audio_features;

EXPORT ER subsystem2_init(void)
{
	T_CSEM	csem = {0};
	T_CMPF	cmpf = {0};

	/* Semaphore: a counter of free "slots".  The producer takes one
	   (tk_wai_sem) before each sample; the consumer gives one back
	   (tk_sig_sem).  It never exceeds the number of memory blocks, so
	   the producer can never run out of memory. */
	csem.sematr  = TA_TFIFO;	/* waiting tasks queue in FIFO order */
	csem.isemcnt = S2_POOL_COUNT;	/* initial count */
	csem.maxsem  = S2_POOL_COUNT;	/* maximum count */
	sem_slots = tk_cre_sem(&csem);
	if (sem_slots < E_OK) {
		return sem_slots;
	}

	/* Fixed-size memory pool: S2_POOL_COUNT blocks, each exactly one
	   SAMPLE_MSG.  Faster and more predictable than malloc(). */
	cmpf.mpfatr = TA_TFIFO | TA_RNG3;
	cmpf.mpfcnt = S2_POOL_COUNT;		/* number of blocks */
	cmpf.blfsz  = sizeof(SAMPLE_MSG);	/* size of one block */
	mpf_samples = tk_cre_mpf(&cmpf);
	if (mpf_samples<0) return mpf_samples;
	T_CMBF buffer={0};
	buffer.maxmsz=sizeof(audio_features_t);
	buffer.bufsz=2*(4+sizeof(audio_features_t));
	mbf_audio_features=tk_cre_mbf(&buffer);
	return mbf_audio_features<0?mbf_audio_features:E_OK;
}

EXPORT ER subsystem2_start(void)
{
	/* Pinned to core 1 (TP_PRC2): samples cross to subsystem 3 on core 0 */
	ID tid = app_start_task(producer_task, S2_PRI_PRODUCER, TP_PRC2,
				"producer_task");
	if (tid<0) return tid;
	T_CTSK task={0};
	task.task=(FP)classifier_task; task.itskpri=15;
	task.stksz=4096; task.tskatr=TA_HLNG|TA_RNG3;
#if TK_SUPPORT_SMP
	task.tskatr|=TA_ASSPRC; task.assprc=TP_PRC2;
#endif
	tid=tk_cre_tsk(&task);
	return tid<0?tid:tk_sta_tsk(tid,0);
}
