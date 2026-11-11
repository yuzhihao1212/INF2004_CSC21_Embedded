/*
 * MOSAIC sensing node: reads the environmental sensors and sends protocol v2
 * TELEMETRY to the PC gateway over Wi-Fi (docs/protocol.md). Answers PING and
 * CONFIG from the PC. Audio is not wired in yet, so no audio windows are sent.
 *
 * One application loop, no RTOS. The SDK services Wi-Fi in background IRQs.
 * Receive callbacks only queue packets; CONFIG and logging run in main.
 * Foreground lwIP calls are protected by cyw43_arch_lwip_begin/end.
 * Pins match firmware/tests/mosaic_sensor_test.c.
 */
#include <malloc.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "pico/critical_section.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "dht22.h"
#include "environment.h"
#include "mosaic_protocol.h"
#include "node_config.h"
#include "sensors.h"

#define DHT_PIN 2
#define PIR_PIN 16
#define CO2_UART uart1
#define CO2_TX_PIN 8
#define CO2_RX_PIN 9
#define PIR_INTERVAL_MS 100
#define WIFI_RETRY_MS 15000
#define WIFI_JOIN_TIMEOUT_MS 30000
#define CONTROL_QUEUE_DEPTH 4
#define LED_ON_MS 50

static struct udp_pcb *pcb;
static ip_addr_t pc_addr;
static bool network_ready;   /* Wi-Fi chip up, credentials and PC IP set */
static uint32_t seq;         /* Advances only for datagrams handed to lwIP */
static mosaic_config_t config = MOSAIC_DEFAULT_CONFIG;
static acd1100_t co2;

typedef struct {
    uint16_t len;
    uint8_t bytes[MOSAIC_MAX_DATAGRAM];
} control_packet_t;

/* Fixed storage; a short critical section protects IRQ -> main handoff. */
static control_packet_t control_queue[CONTROL_QUEUE_DEPTH];
static critical_section_t control_lock;
static unsigned control_read, control_write, control_count;
static uint32_t control_drops, telemetry_sent, telemetry_failed;

static uint64_t now_ms(void) {
    return time_us_64() / 1000;
}

static int link_status(void) {
    cyw43_arch_lwip_begin();
    int status = cyw43_tcpip_link_status(&cyw43_state, CYW43_ITF_STA);
    cyw43_arch_lwip_end();
    return status;
}

static const char *link_name(int status) {
    switch (status) {
    case CYW43_LINK_DOWN: return "down";
    case CYW43_LINK_JOIN: return "joining";
    case CYW43_LINK_NOIP: return "waiting for IP (DHCP)";
    case CYW43_LINK_UP: return "connected";
    case CYW43_LINK_FAIL: return "connection failed";
    case CYW43_LINK_NONET: return "network not found";
    case CYW43_LINK_BADAUTH: return "wrong password";
    default: return "unknown";
    }
}

/* Header seq is filled in here so a failed send doesn't use up a number. */
static bool send_to_pc(void *packet, uint16_t len) {
    if (!network_ready) return false;
    cyw43_arch_lwip_begin();
    if (cyw43_tcpip_link_status(&cyw43_state, CYW43_ITF_STA) != CYW43_LINK_UP) {
        cyw43_arch_lwip_end();
        return false;
    }
    ((mosaic_header_t *)packet)->seq = seq;
    struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, len, PBUF_RAM);
    if (!p) {
        cyw43_arch_lwip_end();
        return false;
    }
    memcpy(p->payload, packet, len);
    err_t err = udp_sendto(pcb, p, &pc_addr, MOSAIC_PORT_TELEMETRY);
    pbuf_free(p);
    if (err == ERR_OK) seq++;
    cyw43_arch_lwip_end();
    return err == ERR_OK;
}

static void on_receive(void *arg, struct udp_pcb *upcb, struct pbuf *p,
                       const ip_addr_t *addr, u16_t port) {
    (void)arg; (void)upcb; (void)port;
    uint16_t len = p->tot_len;
    control_packet_t packet = {.len = len};
    /* Copy out of the pbuf: never cast it, it may be unaligned. */
    bool fits = len >= sizeof(mosaic_header_t) && len <= sizeof packet.bytes;
    if (fits) pbuf_copy_partial(p, packet.bytes, len, 0);
    pbuf_free(p);
    if (!fits) return;

    mosaic_header_t h;
    memcpy(&h, packet.bytes, sizeof h);
    if (mosaic_header_check(&h, len) != MOSAIC_ACK_OK) return;
    /* Only the configured PC may talk to this node, and only to this node's ID.
     * Not authentication (an IP can be spoofed), but stops stray senders. */
    if (!ip_addr_cmp(addr, &pc_addr) || h.node_id != MOSAIC_NODE_ID) return;
    if (h.msg_type != MOSAIC_MSG_PING && h.msg_type != MOSAIC_MSG_CONFIG) return;
    critical_section_enter_blocking(&control_lock);
    if (control_count < CONTROL_QUEUE_DEPTH) {
        control_queue[control_write] = packet;
        control_write = (control_write + 1) % CONTROL_QUEUE_DEPTH;
        control_count++;
    } else {
        /* Never block an IRQ on a slow consumer. CONFIG retries recover drops. */
        control_drops++;
    }
    critical_section_exit(&control_lock);
}

static bool take_control(control_packet_t *packet) {
    critical_section_enter_blocking(&control_lock);
    bool available = control_count != 0;
    if (available) {
        *packet = control_queue[control_read];
        control_read = (control_read + 1) % CONTROL_QUEUE_DEPTH;
        control_count--;
    }
    critical_section_exit(&control_lock);
    return available;
}

static void process_control(const control_packet_t *packet) {
    const uint8_t *buf = packet->bytes;
    mosaic_header_t h;
    memcpy(&h, buf, sizeof h);
    uint32_t time = (uint32_t)now_ms();

    if (h.msg_type == MOSAIC_MSG_PING) {
        mosaic_ping_packet_t pong;
        memset(&pong, 0, sizeof pong);
        mosaic_header_init(&pong.header, MOSAIC_MSG_PONG, MOSAIC_NODE_ID,
                           sizeof pong.payload, 0, time);
        memcpy(&pong.payload, buf + sizeof h, sizeof pong.payload);
        send_to_pc(&pong, sizeof pong);
    } else if (h.msg_type == MOSAIC_MSG_CONFIG) {
        mosaic_config_t c;
        memcpy(&c, buf + sizeof h, sizeof c);
        mosaic_config_ack_packet_t ack;
        memset(&ack, 0, sizeof ack);
        mosaic_header_init(&ack.header, MOSAIC_MSG_CONFIG_ACK, MOSAIC_NODE_ID,
                           sizeof ack.payload, 0, time);
        ack.payload.config_version = c.config_version;
        ack.payload.status = (uint8_t)mosaic_config_check(&c, config.config_version);
        if (ack.payload.status == MOSAIC_ACK_OK) {
            /* audio_gain, mode and threshold are stored for when audio is added. */
            config = c;
            co2.interval_ms = c.co2_interval_ms;
            printf("CONFIG %u applied: report %u ms, DHT %u ms, CO2 %u ms\n",
                   c.config_version, c.report_interval_ms, c.dht_interval_ms,
                   c.co2_interval_ms);
        } else if (ack.payload.status == MOSAIC_ACK_STALE_VERSION) {
            printf("CONFIG %u rejected: older than applied version %u\n",
                   c.config_version, config.config_version);
        } else {
            printf("CONFIG %u rejected: value out of range\n", c.config_version);
        }
        send_to_pc(&ack, sizeof ack);
    }
}

/* Join in the background and retry while the link is down, so a Wi-Fi drop
 * during the demo recovers without a reset. */
static void wifi_service(uint64_t now) {
    static uint64_t next_try;
    static uint64_t join_deadline;
    static int last_status = 1000;
    int status = link_status();
    if (status != last_status) {
        printf("Wi-Fi: %s\n", link_name(status));
        if (status == CYW43_LINK_UP) {
            char address[16];
            cyw43_arch_lwip_begin();
            ip4addr_ntoa_r(netif_ip4_addr(netif_default), address, sizeof address);
            cyw43_arch_lwip_end();
            printf("Node %u IP %s, sending to %s:%u\n", MOSAIC_NODE_ID,
                   address, MOSAIC_PC_IP,
                   MOSAIC_PORT_TELEMETRY);
        }
        last_status = status;
    }
    if (status == CYW43_LINK_UP) {
        join_deadline = 0;
        return;
    }
    if (status > CYW43_LINK_DOWN) {
        if (join_deadline && now >= join_deadline) {
            puts("Wi-Fi: join/DHCP timed out; restarting station");
            cyw43_arch_lwip_begin();
            cyw43_arch_disable_sta_mode();
            cyw43_arch_enable_sta_mode();
            cyw43_arch_lwip_end();
            join_deadline = 0;
            next_try = now_ms() + 1000;
        }
        return;
    }
    if (now < next_try) return;
    uint32_t auth = WIFI_PASSWORD[0] ? CYW43_AUTH_WPA2_AES_PSK : CYW43_AUTH_OPEN;
    if (cyw43_arch_wifi_connect_async(WIFI_SSID, WIFI_PASSWORD, auth) != 0)
        printf("Wi-Fi: could not start joining \"%s\"\n", WIFI_SSID);
    next_try = now_ms() + WIFI_RETRY_MS;
    join_deadline = now_ms() + WIFI_JOIN_TIMEOUT_MS;
}

static uint32_t free_heap_bytes(void) {
    extern char __StackLimit, __bss_end__;  /* Heap bounds from the SDK linker script */
    struct mallinfo m = mallinfo();
    return (uint32_t)(&__StackLimit - &__bss_end__) - (uint32_t)m.uordblks;
}

static bool send_telemetry(const environment_record_t *env, unsigned pir_samples,
                           unsigned pir_active, bool first) {
    if (!network_ready || link_status() != CYW43_LINK_UP) return false;
    mosaic_telemetry_packet_t t;
    memset(&t, 0, sizeof t);
    mosaic_header_init(&t.header, MOSAIC_MSG_TELEMETRY, MOSAIC_NODE_ID,
                       sizeof t.payload, 0, (uint32_t)now_ms());
    if (first) t.header.flags = MOSAIC_FLAG_FIRST_SINCE_BOOT;

    /* environment_record_t and the v2 wire format share the same 0.1 units. */
    uint8_t valid = 0;
    if ((env->validity_flags & ENV_DHT_VALID) == ENV_DHT_VALID) {
        t.payload.temperature_x10 = env->temperature_x10;
        t.payload.humidity_x10 = env->humidity_x10;
        valid |= MOSAIC_VALID_TEMP_HUM;
    }
    if (env->validity_flags & ENV_CO2_VALID) {
        t.payload.co2_ppm = env->co2_ppm;
        valid |= MOSAIC_VALID_CO2;
    } else if (env->co2_status == SENSOR_WARMING_UP) {
        valid |= MOSAIC_VALID_CO2_WARMUP;
    }
    if (pir_samples > 0) {
        t.payload.pir_active_pct = (uint8_t)(100u * pir_active / pir_samples);
        valid |= MOSAIC_VALID_PIR;
    }
    t.payload.valid_flags = valid;
    /* audio_window_count stays 0 until the audio task is added. */
    t.payload.config_version = config.config_version;
    t.payload.free_heap_bytes = free_heap_bytes();
    /* RSSI is a synchronous radio command, not a cheap cached field. */
    static uint64_t next_rssi;
    static int8_t cached_rssi;
    uint64_t now = now_ms();
    if (now >= next_rssi) {
        int32_t rssi;
        if (cyw43_wifi_get_rssi(&cyw43_state, &rssi) == 0)
            cached_rssi = (int8_t)rssi;
        next_rssi = now_ms() + 5000;
    }
    t.payload.wifi_rssi_dbm = cached_rssi;
    return send_to_pc(&t, sizeof t);
}

int main(void) {
    stdio_init_all();
    critical_section_init(&control_lock);
    dht22_t dht;
    bool dht_ready = dht22_init(&dht, DHT_PIN);
    environment_pir_init(PIR_PIN);
    acd1100_init(&co2, CO2_UART, CO2_TX_PIN, CO2_RX_PIN);
    bool wifi_chip = cyw43_arch_init() == 0;
    sleep_ms(2000);  /* USB enumeration and DHT22 power-up */

    printf("MOSAIC node %u (protocol v%u)\n", MOSAIC_NODE_ID, MOSAIC_PROTOCOL_VERSION);
    puts("Network: background servicing; queued CONFIG/PING");
    if (!wifi_chip) {
        printf("Wi-Fi chip failed to start: sensors only\n");
    } else if (!WIFI_SSID[0] || !ipaddr_aton(MOSAIC_PC_IP, &pc_addr)) {
        printf("Wi-Fi SSID or PC IP not set at build time: sensors only.\n"
               "See firmware/node/node_config.example.cmake\n");
    } else {
        cyw43_arch_lwip_begin();
        cyw43_arch_enable_sta_mode();
        pcb = udp_new_ip_type(IPADDR_TYPE_V4);
        if (pcb && udp_bind(pcb, IP_ANY_TYPE, MOSAIC_PORT_CONFIG) == ERR_OK) {
            udp_recv(pcb, on_receive, NULL);
            network_ready = true;
        }
        cyw43_arch_lwip_end();
        if (network_ready)
            printf("Joining \"%s\"...\n", WIFI_SSID);
        else
            printf("Could not open UDP port %u: sensors only\n", MOSAIC_PORT_CONFIG);
    }

    environment_record_t env = {0};
    if (!dht_ready)
        environment_apply_dht(&env, SENSOR_RESOURCE_ERROR, 0, 0, (uint32_t)now_ms());
    uint64_t next_pir = 0, next_dht = 0, next_report = 0, led_off = 0;
    unsigned pir_samples = 0, pir_active = 0;
    bool first = true;
    uint64_t next_health = 0;

    while (true) {
        uint64_t now = now_ms();
        if (network_ready) wifi_service(now);
        control_packet_t packet;
        for (unsigned i = 0; i < CONTROL_QUEUE_DEPTH && take_control(&packet); ++i)
            process_control(&packet);

        if (now >= next_pir) {
            environment_pir_read(&env, PIR_PIN);
            pir_samples++;
            pir_active += env.motion;
            next_pir = now + PIR_INTERVAL_MS;
        }
        acd1100_service(&co2, &env);
        dht22_service(&dht, &env);
        if (dht_ready && !dht.active && now >= next_dht) {
            (void)dht22_start(&dht);
            next_dht = now + config.dht_interval_ms;
        }
        /* Sensor service may timestamp samples after the loop-start time. */
        environment_expire(&env, (uint32_t)now_ms());

        if (now >= next_report) {
            if (send_telemetry(&env, pir_samples, pir_active, first)) {
                telemetry_sent++;
                first = false;
                cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);  /* Blink per packet */
                led_off = now + LED_ON_MS;
            } else {
                telemetry_failed++;
            }
            pir_samples = pir_active = 0;
            next_report = now + config.report_interval_ms;
        }
        if (led_off && now >= led_off) {
            cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);
            led_off = 0;
        }
        if (now >= next_health) {
            critical_section_enter_blocking(&control_lock);
            uint32_t dropped = control_drops;
            critical_section_exit(&control_lock);
            printf("Node health: telemetry sent=%lu failed=%lu control drops=%lu\n",
                   (unsigned long)telemetry_sent, (unsigned long)telemetry_failed,
                   (unsigned long)dropped);
            next_health = now + 10000;
        }
        sleep_ms(1);
    }
}
