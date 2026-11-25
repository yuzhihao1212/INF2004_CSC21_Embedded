#include "drv_watchdog.h"

#if S4_WATCHDOG_TIMEOUT_MS
#include "hardware/structs/psm.h"
#include "hardware/structs/watchdog.h"

/* RP2040-E1: the hardware decrements twice per microsecond. */
#define WATCHDOG_LOAD_VALUE (2000u * S4_WATCHDOG_TIMEOUT_MS)
_Static_assert(S4_WATCHDOG_TIMEOUT_MS > 100 && WATCHDOG_LOAD_VALUE <= WATCHDOG_LOAD_BITS,
               "S4 watchdog timeout must fit the RP2040 counter");

void s4_watchdog_arm(void)
{
    watchdog_hw->ctrl = 0;
    /* CLK_REF uses the board's 12 MHz XOSC. Keep the shared timer at 1 MHz. */
    watchdog_hw->tick = WATCHDOG_TICK_ENABLE_BITS | 12u;
    psm_hw->wdsel = PSM_WDSEL_BITS & ~(PSM_WDSEL_ROSC_BITS | PSM_WDSEL_XOSC_BITS);
    watchdog_hw->scratch[4] = 0; /* Normal flash boot after reset. */
    s4_watchdog_feed();
    watchdog_hw->ctrl = WATCHDOG_CTRL_ENABLE_BITS;
}

void s4_watchdog_feed(void)
{
    watchdog_hw->load = WATCHDOG_LOAD_VALUE;
}

uint32_t s4_watchdog_reason(void)
{
    return watchdog_hw->reason;
}
#endif
