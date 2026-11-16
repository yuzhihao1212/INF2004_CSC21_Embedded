/* On-target only: no Results are claimed until a console log is saved. */
#include "subsystem5.h"
#include "../test_report.h"
#if APP_TEST
#include "s5_internal.h"
#include "../../testing/subsystem5/host/s5_cases.h"

static bool live_config_ack(void)
{
    uint8_t bytes[S5_TX_MAX];
    /* Remove telemetry accumulated during the other subsystem tests. */
    while (tk_rcv_mbf(mbf_s5_tx, bytes, TMO_POL) > 0) {}
    mosaic_config_packet_t c = s5_test_config(1);
    c.header.node_id = MOSAIC_NODE_ID;
    if (tk_snd_mbf(mbf_s5_rx, &c, sizeof c, TMO_POL) != E_OK) return false;
    uint64_t end = s5_now_ms() + 200u;
    for (;;) {
        uint64_t now = s5_now_ms();
        if (now >= end) return false;
        INT len = tk_rcv_mbf(mbf_s5_tx, bytes, (TMO)(end - now));
        if (len < (INT)sizeof(mosaic_header_t)) return false;
        mosaic_header_t h;
        memcpy(&h, bytes, sizeof h);
        if (mosaic_header_check(&h, (size_t)len) != MOSAIC_ACK_OK) return false;
        if (h.msg_type == MOSAIC_MSG_TELEMETRY) continue;
        if (h.msg_type == MOSAIC_MSG_CONFIG_ACK && len == (INT)sizeof(mosaic_config_ack_packet_t)) {
            mosaic_config_ack_packet_t ack;
            memcpy(&ack, bytes, sizeof ack);
            mosaic_config_t applied;
            return h.node_id == MOSAIC_NODE_ID && ack.payload.config_version == 1 &&
                ack.payload.status == MOSAIC_ACK_OK && s5_get_config(&applied) == E_OK &&
                memcmp(&applied, &c.payload, sizeof applied) == 0;
        }
    }
}

void subsystem5_test(void)
{
    TEST_INIT();
    TEST_CHECK("S5-U01", s5_test_case(1), "default config version 0, report 1000 ms");
    TEST_CHECK("S5-U02", s5_test_case(2), "valid CONFIG applies and ACKs OK");
    TEST_CHECK("S5-U03", s5_test_case(3), "invalid CONFIG rejected without changes");
    TEST_CHECK("S5-U04", s5_test_case(4), "older version rejected, same version reapplied");
    TEST_CHECK("S5-U05", s5_test_case(5), "wrong node or malformed control ignored");
    TEST_CHECK("S5-U06", s5_test_case(6), "PING echoed as PONG");
    TEST_CHECK("S5-U07", s5_test_case(7), "first flag and shared seq track accepted sends");
    TEST_CHECK("S5-U08", s5_test_case(8), "PIR 3/10 is 30 percent, then invalid");
    TEST_CHECK("S5-U09", s5_test_case(9), "environment expires after 6000 ms");
    TEST_CHECK("S5-U10", s5_test_case(10), "audio bounds, maxima and reserved class guard");
    TEST_CHECK("S5-U11", s5_test_case(11), "dropped telemetry accounts for audio loss");
    TEST_CHECK("S5-U12", live_config_ack(), "live CONFIG gets ACK OK within 200 ms");
    TEST_SUMMARY("subsystem5");
}
#endif
