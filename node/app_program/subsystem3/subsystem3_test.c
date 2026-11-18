/*
 *	subsystem3_test.c
 *	On-target tests for subsystem 3.  Built only with: make TEST=1
 *	Record unit results in testing/subsystem3/TEST_LOG.md and the
 *	INT- result in testing/integration/TEST_LOG.md.
 */

#include "subsystem3.h"
#include "../test_report.h"

#if APP_TEST

LOCAL APP_STATS read_stats(void)
{
	APP_STATS	s;

	tk_loc_mtx(mtx_stats, TMO_FEVR);
	s = app_stats;
	tk_unl_mtx(mtx_stats);
	return s;
}

/* The observer never accesses peripherals and self-deletes after the run. */
LOCAL void environment_observe(INT stacd, void *exinf)
{
    (void)stacd; (void)exinf;
    s3_diagnostic_snapshot_t d;
    for (unsigned i = 0; i < 65; ++i) {
        if (tk_dly_tsk(5000) != E_OK) break;
        if (!s3_diagnostic_read(&d)) continue;
        SYSTIM now;
        if (tk_get_otm(&now) != E_OK) break;
        /* The SMP USB console masks local interrupts for each tm_printf.
         * Keep calls short and let other tasks run between fragments. */
        tm_printf((UB*)"[S3] ms=%u age=%u progress=%u live=%u tid=%d flags=0x%x\n",
            (unsigned)d.record.timestamp_ms,
            (unsigned)((uint32_t)now.lo - d.record.timestamp_ms),
            (unsigned)d.progress, (unsigned)s3_environment_progress(),
            (int)__atomic_load_n(&tid_environment, __ATOMIC_ACQUIRE),
            (unsigned)d.record.validity_flags);
        if (tk_dly_tsk(10) != E_OK) break;
        tm_printf((UB*)"[S3 DHT] ms=%u t10=%d h10=%u ds=%u dok=%u dfail=%u cap=%u dto=%u rec=%u da=%u stop=%u\n",
            (unsigned)d.record.timestamp_ms,
            (int)d.record.temperature_x10, (unsigned)d.record.humidity_x10,
            (unsigned)d.record.dht_status,
            (unsigned)d.counts.dht_ok, (unsigned)d.counts.dht_fail,
            (unsigned)d.counts.dht_captures, (unsigned)d.counts.dht_timeouts,
            (unsigned)d.counts.dht_recoveries, (unsigned)d.dht_active,
            (unsigned)d.dht_stopping);
        if (tk_dly_tsk(10) != E_OK) break;
        tm_printf((UB*)"[S3 CO2] ms=%u co2=%u cs=%u warm=%u cok=%u cto=%u csum=%u cuart=%u\n",
            (unsigned)d.record.timestamp_ms, (unsigned)d.record.co2_ppm,
            (unsigned)d.record.co2_status, (unsigned)d.co2_warmed,
            (unsigned)d.counts.co2_ok, (unsigned)d.counts.co2_timeouts,
            (unsigned)d.counts.co2_checksums, (unsigned)d.counts.co2_protocol_errors);
        if (tk_dly_tsk(10) != E_OK) break;
        tm_printf((UB*)"[S3 PIR] ms=%u pir=%u ps=%u pact=%u s5post=%u s5all=%u\n",
            (unsigned)d.record.timestamp_ms,
            (unsigned)d.record.motion, (unsigned)d.counts.pir_valid_samples,
            (unsigned)d.counts.pir_motion_samples, (unsigned)d.counts.s5_post_errors,
            (unsigned)d.s5_errors);
    }
    tk_exd_tsk();
}

LOCAL void start_environment_observer(void)
{
    T_CTSK task = {0};
    task.task = (FP)environment_observe;
    task.tskatr = TA_HLNG | TA_RNG3;
    task.itskpri = S3_PRI_ENVIRONMENT;
    task.stksz = 4096; /* tm_printf plus the diagnostic snapshot */
#if TK_SUPPORT_SMP
    task.tskatr |= TA_ASSPRC;
    task.assprc = TP_PRC1;
#endif
    ID id = tk_cre_tsk(&task);
    if (id <= 0) {
        tm_printf((UB*)"[S3] observer create failed: %d\n", (int)id);
        return;
    }
    ER er = tk_sta_tsk(id, 0);
    if (er != E_OK) {
        (void)tk_del_tsk(id);
        tm_printf((UB*)"[S3] observer start failed: %d\n", (int)er);
    }
}

EXPORT void subsystem3_test(void)
{
	APP_STATS	before, after;

	TEST_INIT();
	uint32_t progress_before = s3_environment_progress();
	ER delay_result = tk_dly_tsk(500);
	uint32_t progress_after = s3_environment_progress();
	TEST_CHECK("S3-U11", __atomic_load_n(&tid_environment, __ATOMIC_ACQUIRE) > 0 && delay_result == E_OK &&
		   progress_after != progress_before,
		   "environment task executes service iterations");

	/* INT-01 (integration, IF-01): samples from subsystem 2 arrive.
	   At one sample per 300 ms, 2 s should bring at least 5. */
	before = read_stats();
	tk_dly_tsk(2000);
	after = read_stats();
	TEST_CHECK("INT-01", after.received >= before.received + 5,
		   "samples flow from subsystem 2 to subsystem 3");

	/* S3-U01: the statistics are self-consistent */
	TEST_CHECK("S3-U01",
		   after.received > 0 && after.min <= after.max &&
		   after.min >= 0 && after.max <= 100,
		   "min <= max, both within 0..100");

	TEST_SUMMARY("subsystem3");
	/* Manual observations are never reported as automatic PASS. */
	start_environment_observer();
}

#endif /* APP_TEST */
