#include "s4_network.h"

#define S4_STR_(value) #value
#define S4_STR(value) S4_STR_(value)
#define S4_TOPIC_PREFIX "mosaic/node/" S4_STR(MOSAIC_NODE_ID) "/"

const char *s4_mqtt_config_topic(void) { return S4_TOPIC_PREFIX "config"; }
const char *s4_mqtt_telemetry_topic(void) { return S4_TOPIC_PREFIX "telemetry"; }
const char *s4_mqtt_status_topic(void) { return S4_TOPIC_PREFIX "status"; }

static int topic_matches(const char *topic, const char *expected)
{
    if (!topic) return 0;
    while (*expected && *topic == *expected) {
        ++topic;
        ++expected;
    }
    return *topic == *expected;
}

ER s4_mqtt_receive(const char *topic, void *payload, INT length)
{
    if (!topic_matches(topic, s4_mqtt_config_topic()) || !payload ||
        length < (INT)sizeof(mosaic_header_t) || length > (INT)S5_RX_MAX)
        return E_PAR;

    mosaic_header_t header;
    __builtin_memcpy(&header, payload, sizeof header);
    if (header.node_id != MOSAIC_NODE_ID ||
        (header.msg_type != MOSAIC_MSG_CONFIG && header.msg_type != MOSAIC_MSG_PING) ||
        mosaic_header_check(&header, (size_t)length) != MOSAIC_ACK_OK)
        return E_PAR;

    if (mbf_s5_rx <= 0) return E_OBJ;
    return tk_snd_mbf(mbf_s5_rx, payload, length, TMO_POL);
}

INT s4_mqtt_take_outbound(void *payload, UINT capacity)
{
    if (!payload || capacity < S5_TX_MAX) return E_PAR;
    if (mbf_s5_tx <= 0) return E_OBJ;
    return tk_rcv_mbf(mbf_s5_tx, payload, TMO_POL);
}

uint64_t s4_mqtt_report_clock_ms(void)
{
    SYSTIM time;
    tk_get_tim(&time); /* Same clock as S5's sender_time_ms. */
    return ((uint64_t)(uint32_t)time.hi << 32) | time.lo;
}

bool s4_mqtt_report_is_fresh(uint32_t report_ms, uint64_t connected_ms,
                             uint64_t now_ms)
{
    uint32_t age = (uint32_t)now_ms - report_ms;
    return age <= S4_MQTT_REPORT_MAX_AGE_MS && age < now_ms - connected_ms;
}
