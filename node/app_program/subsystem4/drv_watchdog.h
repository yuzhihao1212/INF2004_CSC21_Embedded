#ifndef S4_DRV_WATCHDOG_H
#define S4_DRV_WATCHDOG_H

#include <stdint.h>

/* Set to the load-tested timeout in milliseconds when commissioning a node. */
#ifndef S4_WATCHDOG_TIMEOUT_MS
#define S4_WATCHDOG_TIMEOUT_MS 0
#endif

#if S4_WATCHDOG_TIMEOUT_MS
void s4_watchdog_arm(void);
void s4_watchdog_feed(void);
uint32_t s4_watchdog_reason(void);
#endif

#endif
