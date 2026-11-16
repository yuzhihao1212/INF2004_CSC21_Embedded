#include "s5_internal.h"
#include <string.h>

/* Finish a pending packet even if a poster briefly owns the lock: an audio
 * batch must always have its send result accounted for. Public callers
 * wait at most S5_LOCK_TMO_MS; only this worker retries a lock timeout. */
static ER report_lock(void)
{
    ER er;
    do {
        er = tk_loc_mtx(mtx_s5, S5_LOCK_TMO_MS);
        if (er == E_TMOUT) tk_dly_tsk(1);
    } while (er == E_TMOUT);
    return er;
}

static void count_one(uint32_t *n)
{
    if (*n != UINT32_MAX) ++*n;
}

static ER queue_packet(void *packet, size_t len, uint8_t audio_count)
{
    mosaic_header_t h;
    ER er = report_lock();
    if (er != E_OK) return er;
    memcpy(&h, packet, sizeof h);
    s5_stamp_seq(&s5_state, &h);
    memcpy(packet, &h, sizeof h);
    /* TMO_POL copying <=64 bytes cannot block. Stamp and commit form one
     * transaction; each accepted queue entry consumes exactly one seq. */
    er = tk_snd_mbf(mbf_s5_tx, packet, (INT)len, TMO_POL);
    s5_sent(&s5_state, &h, er == E_OK, audio_count);
    ER unlock = tk_unl_mtx(mtx_s5);
    return unlock == E_OK ? er : unlock;
}

void report_task(INT stacd, void *exinf)
{
    (void)stacd;
    (void)exinf;
    uint32_t accepted = 0, dropped = 0, controls = 0;
    uint64_t now = s5_now_ms();
    ER er = report_lock();
    if (er != E_OK) goto task_error;
    uint64_t deadline = now + s5_state.config.report_interval_ms;
    er = tk_unl_mtx(mtx_s5);
    if (er != E_OK) goto task_error;
    uint64_t health_deadline = now + 10000u;
    for (;;) {
        uint8_t rx[S5_RX_MAX], reply[sizeof(mosaic_ping_packet_t)];
        now = s5_now_ms();
        uint64_t wake = deadline < health_deadline ? deadline : health_deadline;
        TMO wait = now >= wake ? TMO_POL : (TMO)(wake - now);
        INT len = tk_rcv_mbf(mbf_s5_rx, rx, wait);
        if (len > 0) {
            size_t reply_len;
            mosaic_config_t config;
            er = report_lock();
            if (er != E_OK) break;
            s5_control_result_t result = s5_handle_control(&s5_state, rx,
                (size_t)len, (uint32_t)s5_now_ms(), reply, &reply_len);
            config = s5_state.config;
            er = tk_unl_mtx(mtx_s5);
            if (er != E_OK) break;
            if (result != S5_IGNORED) count_one(&controls);
            if (result == S5_CONFIG_APPLIED) {
                tm_printf((UB*)"CONFIG %u applied: report %u ms, DHT %u ms, CO2 %u ms\n",
                    (unsigned)config.config_version, (unsigned)config.report_interval_ms,
                    (unsigned)config.dht_interval_ms, (unsigned)config.co2_interval_ms);
            } else if (result == S5_CONFIG_REJECTED) {
                mosaic_config_ack_packet_t ack;
                memcpy(&ack, reply, sizeof ack);
                tm_printf((UB*)"CONFIG %u rejected: %s\n",
                    (unsigned)ack.payload.config_version,
                    ack.payload.status == MOSAIC_ACK_STALE_VERSION ?
                    "older than applied version" : "value out of range");
            }
            if (reply_len) {
                er = queue_packet(reply, reply_len, 0);
                if (er != E_OK && er != E_TMOUT) break;
            }
        } else if (len != E_TMOUT) {
            er = len;
            break;
        }
        now = s5_now_ms();
        if (now >= deadline) {
            mosaic_telemetry_packet_t packet;
            uint16_t interval;
            er = report_lock();
            if (er != E_OK) break;
            s5_build_telemetry(&s5_state, now, &packet);
            interval = s5_state.config.report_interval_ms;
            er = tk_unl_mtx(mtx_s5);
            if (er != E_OK) break;
            er = queue_packet(&packet, sizeof packet, packet.payload.audio_window_count);
            if (er == E_OK) count_one(&accepted);
            else if (er == E_TMOUT) count_one(&dropped);
            else break;
            deadline += interval;
            now = s5_now_ms();
            /* Changed intervals apply after the currently scheduled deadline.
             * Preserve cadence unless more than one interval behind. */
            if (now > deadline && now - deadline > interval) deadline = now + interval;
        }
        if (now >= health_deadline) {
            mosaic_config_t config;
            er = report_lock();
            if (er != E_OK) break;
            config = s5_state.config;
            er = tk_unl_mtx(mtx_s5);
            if (er != E_OK) break;
            tm_printf((UB*)"S5 health: reports accepted=%lu dropped=%lu control=%lu config=%u\n",
                (unsigned long)accepted, (unsigned long)dropped,
                (unsigned long)controls, (unsigned)config.config_version);
            health_deadline = now + 10000u;
        }
    }
task_error:
    CHECK(er, "report_task");
    tk_ext_tsk();
}
