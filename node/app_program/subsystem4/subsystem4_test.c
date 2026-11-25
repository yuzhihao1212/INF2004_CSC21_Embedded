/*
 *	subsystem4_test.c
 *	On-target tests for subsystem 4.  Built only with: make TEST=1
 *	Record unit results in testing/subsystem4/TEST_LOG.md and the
 *	INT- result in testing/integration/TEST_LOG.md.
 */

#include "subsystem4.h"
#include "s4_network.h"
#include "../test_report.h"

#if APP_TEST

EXPORT void subsystem4_test(void)
{
	T_RMBF	rmbf;
	UW	before;

	TEST_INIT();

	/* S4-U01: the message buffer accepts the documented line length */
	TEST_CHECK("S4-U01",
		   tk_ref_mbf(mbf_summary, &rmbf) == E_OK &&
		   rmbf.maxmsz == S4_SUMMARY_MAX,
		   "message buffer max line = S4_SUMMARY_MAX");
	const uint64_t wrap = UINT64_C(1) << 32;
	TEST_CHECK("S4-U03",
		   s4_mqtt_report_is_fresh(1, wrap - 2, wrap + 3) &&
		   !s4_mqtt_report_is_fresh(UINT32_MAX - 2, wrap - 2, wrap + 3) &&
		   !s4_mqtt_report_is_fresh(10, 10, 20) &&
		   s4_mqtt_report_is_fresh(20, 10, 20 + S4_MQTT_REPORT_MAX_AGE_MS) &&
		   !s4_mqtt_report_is_fresh(20, 10, 21 + S4_MQTT_REPORT_MAX_AGE_MS),
		   "telemetry freshness rejects backlog and expiry, including clock wrap");

	/* INT-02 (integration, IF-03): summary lines from subsystem 3 reach
	   the monitor.  One line per 5 samples = one per 1.5 s. */
	before = s4_lines_received;
	tk_dly_tsk(3500);
	TEST_CHECK("INT-02", s4_lines_received >= before + 2,
		   "summary lines flow from subsystem 3 to subsystem 4");

	TEST_SUMMARY("subsystem4");
}

#endif /* APP_TEST */
