#ifndef S4_HEALTH_H
#define S4_HEALTH_H

#include "../app.h"

#define S4_HEALTH_NETWORK     1u
#define S4_HEALTH_ENVIRONMENT 2u
#define S4_HEALTH_AUDIO       4u
#define S4_HEALTH_REPORT      8u
#define S4_HEALTH_ALL         15u

/* Report actual task progress, even when the broker is disconnected. */
ER s4_health_mark(UINT bits);
/* Only the watchdog supervisor should consume progress. E_TMOUT means a
 * required task hasn't made progress; its peers' bits are preserved. */
ER s4_health_take(UINT required);
ER s4_health_init(void);

#endif
