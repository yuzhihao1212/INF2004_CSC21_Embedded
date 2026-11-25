#ifndef S4_NETWORK_H
#define S4_NETWORK_H

#include <stdbool.h>
#include "../subsystem5/subsystem5.h"

/* Called only by the MQTT owner task. The inbound payload must be complete.
 * Inbound returns E_OK when queued; outbound returns its byte count or a
 * kernel error. The caller owns the buffers and does the actual publish. */
const char *s4_mqtt_config_topic(void);
const char *s4_mqtt_telemetry_topic(void);
const char *s4_mqtt_status_topic(void);
ER s4_mqtt_receive(const char *topic, void *payload, INT length);
INT s4_mqtt_take_outbound(void *payload, UINT capacity);
/* TELEMETRY uses the S5 system-time clock, including its 32-bit wire wrap. */
#define S4_MQTT_REPORT_MAX_AGE_MS 1000u
uint64_t s4_mqtt_report_clock_ms(void);
bool s4_mqtt_report_is_fresh(uint32_t report_ms, uint64_t connected_ms,
                             uint64_t now_ms);

#endif
