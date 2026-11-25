#include "s4_health.h"
#include "drv_watchdog.h"

#define HEALTH_POLL_MS 100u
#define HEALTH_LOG_MS 10000u

static ID progress;

ER s4_health_init(void)
{
    T_CFLG flag = {0};
    flag.flgatr = TA_TFIFO;
    progress = tk_cre_flg(&flag);
    return progress < E_OK ? progress : E_OK;
}

ER s4_health_mark(UINT bits)
{
    if (!bits || (bits & ~S4_HEALTH_ALL)) return E_PAR;
    if (progress <= 0) return E_OBJ;
    return tk_set_flg(progress, bits);
}

ER s4_health_take(UINT required)
{
    UINT seen;
    if (!required || (required & ~S4_HEALTH_ALL)) return E_PAR;
    if (progress <= 0) return E_OBJ;
    return tk_wai_flg(progress, required, TWF_ANDW | TWF_BITCLR, &seen, TMO_POL);
}

void s4_health_task(INT stacd, void *exinf)
{
    (void)stacd;
    (void)exinf;
    const UINT bits[] = {S4_HEALTH_AUDIO, S4_HEALTH_CLASSIFIER,
                         S4_HEALTH_ENVIRONMENT, S4_HEALTH_REPORT};
    enum { TASK_COUNT = sizeof bits / sizeof bits[0] };
    UW last[TASK_COUNT] = {0}, max_gap[TASK_COUNT] = {0};
    UINT seen = 0, pending = 0;
    UW last_log = 0;
    ER er;
#if S4_WATCHDOG_TIMEOUT_MS
    BOOL armed = FALSE;
    tm_printf((UB*)"S4 watchdog previous boot reason=%u\n", s4_watchdog_reason());
#endif

    for (;;) {
        SYSTIM time;
        er = tk_get_otm(&time);
        if (er != E_OK) break;
        for (unsigned i = 0; i < TASK_COUNT; ++i) {
            er = s4_health_take(bits[i]);
            if (er != E_OK && er != E_TMOUT) goto task_error;
            if (seen & bits[i]) {
                UW gap = time.lo - last[i];
                if (gap > max_gap[i]) max_gap[i] = gap;
            }
            if (er == E_OK) {
                last[i] = time.lo;
                seen |= bits[i];
                pending |= bits[i];
            }
#if S4_WATCHDOG_TIMEOUT_MS
            if (!armed && time.lo - last[i] >= S4_WATCHDOG_TIMEOUT_MS)
                pending &= ~bits[i];
#endif
        }
        if (pending == S4_HEALTH_LOCAL) {
            pending = 0;
#if S4_WATCHDOG_TIMEOUT_MS
            if (armed) {
                s4_watchdog_feed();
            } else {
                armed = TRUE;
                s4_watchdog_arm();
                tm_printf((UB*)"S4 watchdog armed: %u ms\n", S4_WATCHDOG_TIMEOUT_MS);
            }
#endif
        }
        if (time.lo - last_log >= HEALTH_LOG_MS) {
            tm_printf((UB*)"S4 progress seen=0x%x max_gap_ms audio=%u classifier=%u env=%u report=%u\n",
                      seen, max_gap[0], max_gap[1], max_gap[2], max_gap[3]);
            last_log = time.lo;
        }
        er = tk_dly_tsk(HEALTH_POLL_MS);
        if (er != E_OK) break;
    }
task_error:
    CHECK(er, "S4 health supervisor");
    tk_ext_tsk();
}
