/* Subsystem 5 — Node config and telemetry. Owner: ZhiHao (yuzhihao1212).
 * Student ID: 2503001. */
#ifndef SUBSYSTEM5_H
#define SUBSYSTEM5_H
#include "../../../firmware/common/include/mosaic_protocol.h"
/* As in the template's sys_arch.c: use libc's size_t and suppress the
 * kernel's alternative typedef. Include this header BEFORE app.h or any
 * other subsystem header in a TU using the protocol/libc headers. */
#ifndef PROHIBIT_DEF_SIZE_T
#define PROHIBIT_DEF_SIZE_T
#define S5_UNDEF_PROHIBIT_SIZE_T
#endif
#include "../app.h"
#ifdef S5_UNDEF_PROHIBIT_SIZE_T
#undef PROHIBIT_DEF_SIZE_T
#undef S5_UNDEF_PROHIBIT_SIZE_T
#endif

#if __has_include("s5_node_id.h")
#include "s5_node_id.h"
#endif
#ifndef MOSAIC_NODE_ID
#define MOSAIC_NODE_ID 1
#endif
#if MOSAIC_NODE_ID < 1 || MOSAIC_NODE_ID > MOSAIC_MAX_NODES
#error "MOSAIC_NODE_ID must be in 1..MOSAIC_MAX_NODES"
#endif

#define S5_PRI_REPORT 20
#define S5_LOCK_TMO_MS 10
#define S5_QUEUE_DEPTH 4
#define S5_RX_MAX MOSAIC_MAX_DATAGRAM
#define S5_TX_MAX sizeof(mosaic_telemetry_packet_t)
/* kernel/tkernel/messagebuf.h: HEADER is INT (4 bytes); ROUNDSZ rounds
 * payloads to 4 bytes. Both maxima are aligned: RX = 4*(4+128) = 528;
 * TX = 4*(4+64) = 272 bytes. */
#define S5_RX_BUFSZ (S5_QUEUE_DEPTH * (4u + S5_RX_MAX))
#define S5_TX_BUFSZ (S5_QUEUE_DEPTH * (4u + S5_TX_MAX))

/* S4 checks IDs > 0 before use (Wi-Fi can start before usermain).
 * Only inside cyw43_utk_task, S4 sends mbf_s5_rx and receives mbf_s5_tx
 * with TMO_POL only. Each message is one complete protocol v2 datagram;
 * S4 selects the MQTT topic using header.msg_type.
 * Until S4 drains TX it fills after 4 reports. Later reports are dropped
 * and counted without consuming seq. Accepted means queued; downstream
 * transport failures belong to S4. */
IMPORT ID mtx_s5;
IMPORT ID mbf_s5_rx;
IMPORT ID mbf_s5_tx;

/* Task context only, never interrupt context. Bounded mutex wait; E_TMOUT
 * means no state was accessed. Arguments are copied before returning. */
IMPORT ER s5_get_config(mosaic_config_t *out);
IMPORT ER s5_post_environment(int16_t temperature_x10, uint16_t humidity_x10,
                              uint16_t co2_ppm, uint8_t valid_bits);
IMPORT ER s5_post_pir(uint32_t samples, uint32_t active);
IMPORT ER s5_post_audio_window(const mosaic_audio_window_t *window,
                               uint32_t dsp_us, uint32_t inference_us);
IMPORT ER s5_audio_dropped(uint16_t windows);
IMPORT ER s5_post_health(int8_t rssi_dbm, uint8_t cpu_load_pct,
                         uint32_t free_heap_bytes);
#endif
