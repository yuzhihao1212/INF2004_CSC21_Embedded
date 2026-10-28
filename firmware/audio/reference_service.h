#ifndef MOSAIC_REFERENCE_SERVICE_H
#define MOSAIC_REFERENCE_SERVICE_H
#include <stddef.h>
/* Temporary USB bridge to the same portable decision API networking can call.
 * @RESET\n or @PAIR,id,now,ref_time,ref_rms,ref_votes,ref_valid,student_time,
 * student_rms,student_votes,student_valid\n. Times are common-clock microseconds.
 */
int reference_service_receiving(void);
void reference_service_feed(int character,void (*write)(const char *,size_t));
#endif
