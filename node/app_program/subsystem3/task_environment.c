#include "../subsystem5/subsystem5.h"
#include "subsystem3.h"
#include "environment_service.h"
#include "s3_time.h"
#if TM_WIFI_CYW43
#include "cyw43_utk.h"
#endif

static s3_service_t service; /* single owning task; inspect with debugger */
static uint32_t progress;

uint32_t s3_environment_progress(void)
{
    return __atomic_load_n(&progress, __ATOMIC_ACQUIRE);
}

static void environment_exit(ER er, const char *what)
{
    /* Do not reuse or unclaim hardware on exit. A pending abort may still
     * write to service.dht.pulses; that object has static lifetime. */
    if (service.dht.active && !service.dht.stopping) {
        s3_dht_hw_stop(&service.dht);
        service.dht.stopping = true;
    }
    __atomic_store_n(&tid_environment, 0, __ATOMIC_RELEASE);
    CHECK(er, what);
    tk_ext_tsk();
}

static ER monotonic_ms(uint32_t *now)
{
    SYSTIM time;
    ER er = tk_get_otm(&time); /* operating time is unaffected by tk_set_tim */
    if (er == E_OK) *now = (uint32_t)time.lo;
    return er;
}

void environment_task(INT stacd, void *exinf)
{
    (void)stacd; (void)exinf;
    uint32_t now;
    ER er = monotonic_ms(&now);
    if (er != E_OK) { environment_exit(er, "S3 clock"); return; }
    s3_service_init(&service, now);
    for (;;) {
        er = monotonic_ms(&now);
        if (er != E_OK) { environment_exit(er, "S3 clock"); return; }
        bool pio_available = true;
#if TM_WIFI_CYW43
        /* Allowed read-only status API. Let the radio allocate first; no
         * network calls and no blocking dependency on successful association. */
        T_CYW43_UTK_STATUS status;
        cyw43_utk_get_status(&status);
        pio_available = status.init_complete != 0;
#endif
        s3_service_step(&service, now, pio_available);
        /* One writer, aligned 32-bit atomic load/store; safe across cores. */
        uint32_t count = __atomic_load_n(&progress, __ATOMIC_RELAXED);
        __atomic_store_n(&progress, count + 1u, __ATOMIC_RELEASE);
        er = monotonic_ms(&now); /* S5 calls may have taken up to 30 ms */
        if (er != E_OK) { environment_exit(er, "S3 clock"); return; }
        s3_service_start_due(&service, now);
        /* Kernel tick is 10 ms; this is cooperative polling, not a busy wait. */
        er = tk_dly_tsk(10);
        if (er != E_OK) { environment_exit(er, "S3 delay"); return; }
    }
}
