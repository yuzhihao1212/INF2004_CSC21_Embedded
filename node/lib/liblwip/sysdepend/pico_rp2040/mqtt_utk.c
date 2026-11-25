/* All lwIP calls run inside cyw43_utk_task via its timeout processing. */
#include "lwip/apps/mqtt.h"
#include "lwip/ip_addr.h"
#include "lwip/timeouts.h"
#include "lwip/sys.h"
#include "wifi_secrets.h"
#include "mqtt_utk.h"
#include "../../../../../app_program/subsystem4/s4_network.h"

static mqtt_client_t *client;
static ip_addr_t broker_addr;
static u8_t connecting, subscribed;
static bool announced;
static char rx_topic[64];
static u8_t rx_data[MOSAIC_MAX_DATAGRAM];
static unsigned rx_len, rx_expected;
static int rx_invalid;
static u8_t pending[S5_TX_MAX];
static INT pending_len;
static uint64_t connected_at_ms;
static bool boot_report_pending;
static char client_id[32];

static void pump(void *arg);
static void incoming_publish(void *arg,const char *topic,u32_t length)
{
    (void)arg;
    unsigned i=0;
    for(;i<sizeof(rx_topic)-1 && topic[i];++i) rx_topic[i]=topic[i];
    rx_topic[i]=0;
    rx_len=0; rx_expected=length;
    rx_invalid=topic[i]!=0 || length>sizeof(rx_data);
}
static void incoming_data(void *arg,const u8_t *data,u16_t len,u8_t flags)
{
    (void)arg;
    if (!rx_invalid && rx_len+len<=sizeof(rx_data)) {
        for(unsigned i=0;i<len;++i) rx_data[rx_len++]=data[i];
    } else rx_invalid=1;
    if ((flags & MQTT_DATA_FLAG_LAST) && !rx_invalid && rx_len==rx_expected) {
        ER er=s4_mqtt_receive(rx_topic,rx_data,(INT)rx_len);
        if(er<E_OK) tm_printf((UB*)"mqtt: control rejected/queue full %d\n",er);
    }
}
static void subscribed_cb(void *arg,err_t result)
{
    (void)arg;
    subscribed=result==ERR_OK;
    tm_printf((UB*)"mqtt: CONFIG subscription result=%d\n",result);
}
static void publish_cb(void *arg,err_t result)
{
    (void)arg;
    if(result!=ERR_OK) tm_printf((UB*)"mqtt: publish result=%d\n",result);
}
static void pump(void *arg)
{
    (void)arg;
    if(client && mqtt_client_is_connected(client)) {
        if (!announced) {
            announced = mqtt_publish(client, s4_mqtt_status_topic(), "online",
                                     6, 1, 1, publish_cb, NULL) == ERR_OK;
            if (!announced) goto schedule;
        }
        if(!subscribed)
            (void)mqtt_subscribe(client,s4_mqtt_config_topic(),1,subscribed_cb,NULL);
        /* Bound work to keep the single radio task responsive. Retain a
         * dequeued packet if lwIP's output buffer is temporarily full. */
        for(unsigned i=0;i<4;++i) {
            if(!pending_len) {
                INT len=s4_mqtt_take_outbound(pending,sizeof pending);
                if(len<=0) break;
                pending_len=len;
            }
            mosaic_header_t header;
            __builtin_memcpy(&header, pending, sizeof header);
            if (header.msg_type == MOSAIC_MSG_TELEMETRY) {
                boot_report_pending |= (header.flags & MOSAIC_FLAG_FIRST_SINCE_BOOT) != 0;
                if (!s4_mqtt_report_is_fresh(header.sender_time_ms, connected_at_ms,
                                            s4_mqtt_report_clock_ms())) {
                    pending_len = 0;
                    continue;
                }
                if (boot_report_pending) {
                    header.flags |= MOSAIC_FLAG_FIRST_SINCE_BOOT;
                    __builtin_memcpy(pending, &header, sizeof header);
                }
            }
            err_t er=mqtt_publish(client,s4_mqtt_telemetry_topic(),pending,
                                  (u16_t)pending_len,0,0,publish_cb,NULL);
            if(er!=ERR_OK) break;
            if (header.msg_type == MOSAIC_MSG_TELEMETRY) boot_report_pending = false;
            pending_len=0;
        }
    }
schedule:
    sys_timeout(50,pump,NULL);
}
static void connection_cb(mqtt_client_t *c,void *arg,mqtt_connection_status_t status)
{
    (void)c; (void)arg;
    connecting=0; subscribed=0;
    if(status==MQTT_CONNECT_ACCEPTED) {
        announced = false;
        connected_at_ms = s4_mqtt_report_clock_ms();
        mqtt_set_inpub_callback(client,incoming_publish,incoming_data,NULL);
        tm_printf((UB*)"mqtt: node %u connected\n",MOSAIC_NODE_ID);
    } else {
        tm_printf((UB*)"mqtt: connection status=%d\n",status);
    }
}
int mqtt_utk_is_connected(void)
{
    return client != NULL && mqtt_client_is_connected(client);
}

void mqtt_utk_poll(int wifi_up)
{
    static u32_t next_attempt;
    static bool pump_started;
    if (!wifi_up) {
        /* An old TCP session can remain connected after association drops. */
        if (connecting || mqtt_utk_is_connected()) mqtt_disconnect(client);
        connecting = 0;
        return;
    }
    u32_t now=sys_now();
    if (!pump_started) {
        pump_started = true;
        sys_timeout(1, pump, NULL);
    }
    if(connecting || (client && mqtt_client_is_connected(client))) return;
    if((s32_t)(now-next_attempt)<0) return;
    next_attempt=now+3000;
    if(!client) client=mqtt_client_new();
    if(!client) return;
    if(!ip4addr_aton(MQTT_BROKER_IP,ip_2_ip4(&broker_addr))) return;
    IP_SET_TYPE(&broker_addr,IPADDR_TYPE_V4);
    /* Unique IDs prevent one Pico disconnecting another at the broker. */
    tm_sprintf((UB*)client_id,(const UB*)"mosaic-node-%u",MOSAIC_NODE_ID);
    struct mqtt_connect_client_info_t info={0};
    info.client_id=client_id;
    info.keep_alive=30;
    info.will_topic=s4_mqtt_status_topic();
    info.will_msg="offline"; info.will_qos=1; info.will_retain=1;
    connecting=1;
    if(mqtt_client_connect(client,&broker_addr,MQTT_BROKER_PORT,
                           connection_cb,NULL,&info)!=ERR_OK) connecting=0;
}
