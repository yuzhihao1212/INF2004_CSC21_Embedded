/* Private to subsystem 5. Other subsystems must use the public interface. */
#ifndef S5_INTERNAL_H
#define S5_INTERNAL_H
#include "subsystem5.h"
#include "s5_protocol.h"
extern s5_state_t s5_state; /* Access only with mtx_s5 held. */
uint64_t s5_now_ms(void);
void report_task(INT stacd, void *exinf);
#endif
