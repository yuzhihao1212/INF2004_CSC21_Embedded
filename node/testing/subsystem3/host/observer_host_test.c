/* Exercise the real test runner and observer using kernel/console doubles. */
#include "startup_mock.h"
#include "utk_mock.h"
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

typedef unsigned char UB;
#define TMO_FEVR (-1)
#define TEST_REPORT_H
#define TEST_INIT() ((void)0)
#define TEST_CHECK(id, cond, desc) ((void)(cond))
#define TEST_SUMMARY(name) ((void)0)
ID tk_cre_tsk(const T_CTSK *task);
ER tk_sta_tsk(ID id, INT code);
ER tk_del_tsk(ID id);
void tk_exd_tsk(void);
INT tm_printf(const UB *format, ...);

#include "../../../app_program/subsystem3/subsystem3_test.c"

ID mtx_stats = 1, tid_environment = 2;
APP_STATS app_stats = {10, 1, 10, 30};
static T_CTSK created;
static ID create_result = 3;
static ER start_result;
static unsigned deletes, exits, waits_5s, waits_10ms, prints, reads;

ID tk_cre_tsk(const T_CTSK *task) { created = *task; return create_result; }
ER tk_sta_tsk(ID id, INT code) { assert(id == 3 && code == 0); return start_result; }
ER tk_del_tsk(ID id) { assert(id == 3); ++deletes; return E_OK; }
void tk_exd_tsk(void) { ++exits; }
ER tk_loc_mtx(ID id, int timeout) { (void)id; (void)timeout; return E_OK; }
ER tk_unl_mtx(ID id) { (void)id; return E_OK; }
ER tk_get_otm(SYSTIM *time) { time->lo = 1000; return E_OK; }
ER tk_dly_tsk(unsigned ms)
{
    if (ms == 5000) ++waits_5s;
    if (ms == 10) ++waits_10ms;
    return E_OK;
}
INT tm_printf(const UB *format, ...) { (void)format; ++prints; return 0; }
uint32_t s3_environment_progress(void) { return 12; }
bool s3_diagnostic_read(s3_diagnostic_snapshot_t *out)
{
    memset(out, 0, sizeof *out);
    ++reads;
    return true;
}

int main(void)
{
    /* Starting the observer schedules it; the startup test returns without
     * executing its five-minute loop in the initial task. */
    subsystem3_test();
    assert(created.task && created.itskpri == 17 && created.stksz == 4096);
    assert((created.tskatr & TA_ASSPRC) && created.assprc == TP_PRC1);
    assert(waits_5s == 0 && reads == 0);
    created.task(0, NULL);
    assert(waits_5s == 65 && waits_10ms == 195 && reads == 65);
    assert(prints == 260 && exits == 1);

    create_result = -1;
    subsystem3_test();
    assert(deletes == 0);
    create_result = 3;
    start_result = E_OBJ;
    subsystem3_test();
    assert(deletes == 1);
    puts("PASS S3-U32: observer startup, schedule, self-delete and failure cleanup (simulated)");
    return 0;
}
