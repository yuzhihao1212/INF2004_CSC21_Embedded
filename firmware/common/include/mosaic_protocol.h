/*
 * MOSAIC node <-> PC wire protocol, version 1.
 *
 * Specification: docs/protocol.md. The Python mirror is pc/mosaic/protocol.py;
 * any change here must be made there too and MOSAIC_PROTOCOL_VERSION bumped.
 *
 * Every UDP datagram is one mosaic_header_t followed by exactly one payload.
 * All multi-byte fields are little-endian (native on both RP2040 and x86/ARM PCs).
 *
 * The structs are laid out with natural alignment so they contain no padding;
 * the static asserts at the bottom enforce that. Do NOT reorder fields.
 *
 * Receiving: always memcpy() the datagram into one of these structs. Never cast
 * a raw buffer pointer: lwIP buffers may be unaligned, and an unaligned word
 * access hard-faults on the RP2040's Cortex-M0+.
 *
 * Plain C11 and <stdint.h> only, so it builds for both the Pico and the host.
 */
#ifndef MOSAIC_PROTOCOL_H
#define MOSAIC_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MOSAIC_MAGIC            0x534Du  /* "MS" in little-endian byte order */
#define MOSAIC_PROTOCOL_VERSION 1u

#define MOSAIC_PORT_TELEMETRY   5005u    /* PC listens; nodes send TELEMETRY, CONFIG_ACK, PONG */
#define MOSAIC_PORT_CONFIG      5006u    /* Node listens; PC sends CONFIG, PING */

#define MOSAIC_MAX_DATAGRAM     128u     /* Every message is far below one Ethernet/Wi-Fi MTU */

/* ---- Message types --------------------------------------------------- */

typedef enum {
    MOSAIC_MSG_TELEMETRY  = 1,  /* node -> PC, every report interval */
    MOSAIC_MSG_CONFIG     = 2,  /* PC -> node, full configuration snapshot */
    MOSAIC_MSG_CONFIG_ACK = 3,  /* node -> PC, reply to CONFIG */
    MOSAIC_MSG_PING       = 4,  /* PC -> node, latency probe */
    MOSAIC_MSG_PONG       = 5,  /* node -> PC, echoes the PING payload */
} mosaic_msg_type_t;

/* Header flags */
#define MOSAIC_FLAG_FIRST_SINCE_BOOT  (1u << 0)  /* First TELEMETRY after a reset */

/* ---- Common header (16 bytes) ---------------------------------------- */

typedef struct {
    uint16_t magic;         /* MOSAIC_MAGIC */
    uint8_t  version;       /* MOSAIC_PROTOCOL_VERSION */
    uint8_t  msg_type;      /* mosaic_msg_type_t */
    uint8_t  node_id;       /* 1..MOSAIC_MAX_NODES on nodes; 0 when sent by the PC */
    uint8_t  flags;         /* MOSAIC_FLAG_* */
    uint16_t payload_len;   /* Bytes after the header; must equal the type's payload size */
    uint32_t seq;           /* Per-sender counter, +1 per datagram sent; starts at 0 on boot */
    uint32_t sender_time_ms;/* Sender's monotonic clock (ms since boot); not synchronised */
} mosaic_header_t;

#define MOSAIC_MAX_NODES 8u

/* ---- TELEMETRY (40-byte payload) ------------------------------------- */

/* Audio classes. Must match the labels the ML model is trained on. */
typedef enum {
    MOSAIC_AUDIO_UNKNOWN              = 0,  /* Audio invalid, or best class below confidence threshold */
    MOSAIC_AUDIO_BACKGROUND_NOISE     = 1,
    MOSAIC_AUDIO_LECTURER_SPEECH      = 2,
    MOSAIC_AUDIO_STUDENT_CONVERSATION = 3,
    MOSAIC_AUDIO_TRANSIENT_NOISE      = 4,
} mosaic_audio_class_t;

#define MOSAIC_AUDIO_CLASS_COUNT 4u  /* Classes 1..4; probability array index = class - 1 */

/* TELEMETRY valid_flags: a value is only meaningful when its bit is set. */
#define MOSAIC_VALID_TEMP_HUM   (1u << 0)  /* DHT22 read and checksum OK */
#define MOSAIC_VALID_CO2        (1u << 1)  /* CO2 reading current (not stale, not warming up) */
#define MOSAIC_VALID_CO2_WARMUP (1u << 2)  /* CO2 sensor still in warm-up period */
#define MOSAIC_VALID_PIR        (1u << 3)
#define MOSAIC_VALID_AUDIO      (1u << 4)  /* audio_class, probabilities and audio_rms valid */

typedef struct {
    float    temperature_c;
    float    humidity_pct;
    float    audio_rms;              /* Mean RMS of the last classification window (ADC units) */
    uint32_t dsp_time_us;            /* Feature extraction time for the last window */
    uint32_t inference_time_us;      /* ML inference time for the last window */
    uint32_t free_heap_bytes;
    uint16_t co2_ppm;
    uint16_t config_version;         /* Config currently applied; 0 = compiled-in defaults */
    uint16_t audio_overruns;         /* Audio windows dropped since boot (sampling reliability) */
    uint8_t  audio_class;            /* mosaic_audio_class_t */
    uint8_t  pir_active_pct;         /* % of PIR samples showing motion during this interval */
    uint8_t  audio_prob_pct[MOSAIC_AUDIO_CLASS_COUNT]; /* Per-class probability, 0..100 */
    uint8_t  valid_flags;            /* MOSAIC_VALID_* */
    uint8_t  cpu_load_pct;
    int8_t   wifi_rssi_dbm;
    uint8_t  reserved;               /* Send 0 */
} mosaic_telemetry_t;

/* ---- CONFIG (16-byte payload) ---------------------------------------- */

/*
 * Only node-side parameters travel to the nodes. Fusion thresholds (CO2
 * warning level, noise persistence, state transitions, zone mapping) stay on
 * the PC, so changing them never requires talking to a node.
 */
typedef enum {
    MOSAIC_MODE_LECTURE    = 0,
    MOSAIC_MODE_DISCUSSION = 1,
    MOSAIC_MODE_QUIET_WORK = 2,
} mosaic_mode_t;

#define MOSAIC_MODE_COUNT 3u

typedef struct {
    uint16_t config_version;         /* Set by the PC, increases on every change; never 0 */
    uint16_t report_interval_ms;
    uint16_t dht_interval_ms;
    uint16_t co2_interval_ms;
    float    audio_gain;             /* Multiplier applied to samples before feature extraction */
    uint8_t  mode;                   /* mosaic_mode_t */
    uint8_t  audio_conf_threshold_pct; /* Below this, the node reports MOSAIC_AUDIO_UNKNOWN */
    uint8_t  reserved[2];            /* Send 0 */
} mosaic_config_t;

/* Accepted ranges. A node rejects a CONFIG with any field outside them. */
#define MOSAIC_REPORT_INTERVAL_MIN_MS  200u
#define MOSAIC_REPORT_INTERVAL_MAX_MS  10000u
#define MOSAIC_DHT_INTERVAL_MIN_MS     2000u   /* DHT22 cannot be read faster than every 2 s */
#define MOSAIC_DHT_INTERVAL_MAX_MS     60000u
#define MOSAIC_CO2_INTERVAL_MIN_MS     1000u
#define MOSAIC_CO2_INTERVAL_MAX_MS     60000u
#define MOSAIC_AUDIO_GAIN_MIN          0.1f
#define MOSAIC_AUDIO_GAIN_MAX          10.0f

/* Defaults a node uses from boot until its first CONFIG (config_version 0). */
#define MOSAIC_DEFAULT_CONFIG { \
    .config_version = 0, \
    .report_interval_ms = 1000, \
    .dht_interval_ms = 2500, \
    .co2_interval_ms = 2000, \
    .audio_gain = 1.0f, \
    .mode = MOSAIC_MODE_LECTURE, \
    .audio_conf_threshold_pct = 60, \
    .reserved = {0, 0}, \
}

/* ---- CONFIG_ACK (4-byte payload) ------------------------------------- */

typedef enum {
    MOSAIC_ACK_OK            = 0,  /* Applied */
    MOSAIC_ACK_INVALID_VALUE = 1,  /* A field was out of range; nothing applied */
    MOSAIC_ACK_UNSUPPORTED   = 2,  /* Unknown protocol version or message */
} mosaic_ack_status_t;

typedef struct {
    uint16_t config_version;         /* Echo of the CONFIG being answered */
    uint8_t  status;                 /* mosaic_ack_status_t */
    uint8_t  reserved;               /* Send 0 */
} mosaic_config_ack_t;

/* ---- PING / PONG (8-byte payload) ------------------------------------ */

typedef struct {
    uint64_t pc_time_us;             /* Set by the PC; the node echoes it back unchanged */
} mosaic_ping_t;

/* ---- Full datagrams --------------------------------------------------- */

typedef struct { mosaic_header_t header; mosaic_telemetry_t  payload; } mosaic_telemetry_packet_t;
typedef struct { mosaic_header_t header; mosaic_config_t     payload; } mosaic_config_packet_t;
typedef struct { mosaic_header_t header; mosaic_config_ack_t payload; } mosaic_config_ack_packet_t;
typedef struct { mosaic_header_t header; mosaic_ping_t       payload; } mosaic_ping_packet_t;

/* ---- Helpers ---------------------------------------------------------- */

static inline void mosaic_header_init(mosaic_header_t *h, mosaic_msg_type_t type,
                                      uint8_t node_id, uint16_t payload_len,
                                      uint32_t seq, uint32_t sender_time_ms) {
    h->magic = MOSAIC_MAGIC;
    h->version = MOSAIC_PROTOCOL_VERSION;
    h->msg_type = (uint8_t)type;
    h->node_id = node_id;
    h->flags = 0;
    h->payload_len = payload_len;
    h->seq = seq;
    h->sender_time_ms = sender_time_ms;
}

/* Expected payload size for a message type, or 0 if the type is unknown. */
static inline uint16_t mosaic_payload_size(uint8_t msg_type) {
    switch (msg_type) {
    case MOSAIC_MSG_TELEMETRY:  return sizeof(mosaic_telemetry_t);
    case MOSAIC_MSG_CONFIG:     return sizeof(mosaic_config_t);
    case MOSAIC_MSG_CONFIG_ACK: return sizeof(mosaic_config_ack_t);
    case MOSAIC_MSG_PING:
    case MOSAIC_MSG_PONG:       return sizeof(mosaic_ping_t);
    default:                    return 0;
    }
}

/*
 * Check a received datagram's header. Returns MOSAIC_ACK_OK if the header is
 * well-formed and len matches the header plus that type's payload size.
 */
static inline mosaic_ack_status_t mosaic_header_check(const mosaic_header_t *h, size_t len) {
    if (h->magic != MOSAIC_MAGIC || h->version != MOSAIC_PROTOCOL_VERSION) {
        return MOSAIC_ACK_UNSUPPORTED;
    }
    uint16_t expected = mosaic_payload_size(h->msg_type);
    if (expected == 0) return MOSAIC_ACK_UNSUPPORTED;
    if (h->payload_len != expected || len != sizeof(mosaic_header_t) + expected) {
        return MOSAIC_ACK_INVALID_VALUE;
    }
    return MOSAIC_ACK_OK;
}

/* Range-check a CONFIG before applying it. */
static inline mosaic_ack_status_t mosaic_config_check(const mosaic_config_t *c) {
    if (c->config_version == 0) return MOSAIC_ACK_INVALID_VALUE;
    if (c->report_interval_ms < MOSAIC_REPORT_INTERVAL_MIN_MS ||
        c->report_interval_ms > MOSAIC_REPORT_INTERVAL_MAX_MS) return MOSAIC_ACK_INVALID_VALUE;
    if (c->dht_interval_ms < MOSAIC_DHT_INTERVAL_MIN_MS ||
        c->dht_interval_ms > MOSAIC_DHT_INTERVAL_MAX_MS) return MOSAIC_ACK_INVALID_VALUE;
    if (c->co2_interval_ms < MOSAIC_CO2_INTERVAL_MIN_MS ||
        c->co2_interval_ms > MOSAIC_CO2_INTERVAL_MAX_MS) return MOSAIC_ACK_INVALID_VALUE;
    /* Written so that NaN fails both comparisons and is rejected. */
    if (!(c->audio_gain >= MOSAIC_AUDIO_GAIN_MIN && c->audio_gain <= MOSAIC_AUDIO_GAIN_MAX)) {
        return MOSAIC_ACK_INVALID_VALUE;
    }
    if (c->mode >= MOSAIC_MODE_COUNT) return MOSAIC_ACK_INVALID_VALUE;
    if (c->audio_conf_threshold_pct > 100) return MOSAIC_ACK_INVALID_VALUE;
    return MOSAIC_ACK_OK;
}

/* ---- Layout guarantees ------------------------------------------------ */

#ifdef __cplusplus
#define MOSAIC_STATIC_ASSERT static_assert
#else
#define MOSAIC_STATIC_ASSERT _Static_assert
#endif

MOSAIC_STATIC_ASSERT(sizeof(float) == 4, "float must be IEEE-754 single precision");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_header_t) == 16, "header layout changed");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_telemetry_t) == 40, "telemetry layout changed");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_config_t) == 16, "config layout changed");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_config_ack_t) == 4, "config ack layout changed");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_ping_t) == 8, "ping layout changed");
MOSAIC_STATIC_ASSERT(offsetof(mosaic_telemetry_t, co2_ppm) == 24, "telemetry layout changed");
MOSAIC_STATIC_ASSERT(offsetof(mosaic_telemetry_t, audio_prob_pct) == 32, "telemetry layout changed");
MOSAIC_STATIC_ASSERT(offsetof(mosaic_config_t, audio_gain) == 8, "config layout changed");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_telemetry_packet_t) == 56, "telemetry packet has padding");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_config_packet_t) == 32, "config packet has padding");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_config_ack_packet_t) == 20, "config ack packet has padding");
MOSAIC_STATIC_ASSERT(sizeof(mosaic_ping_packet_t) == 24, "ping packet has padding");

#ifdef __cplusplus
}
#endif

#endif /* MOSAIC_PROTOCOL_H */
