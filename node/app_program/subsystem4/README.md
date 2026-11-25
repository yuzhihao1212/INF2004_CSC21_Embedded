# Subsystem 4: MQTT handoff and node health

In the shared MQTT service, subscribe to `s4_mqtt_config_topic()` at QoS 1
after each successful connection. Pass the complete inbound message and its
original topic to `s4_mqtt_receive()`. This includes both CONFIG and PING.
Once connected, drain `s4_mqtt_take_outbound()` into an S5_TX_MAX-byte buffer
and publish each returned datagram on `s4_mqtt_telemetry_topic()` at QoS 0
without retain. The MQTT service publishes the link announcement before
draining the queue and sets the offline last will. After each connection,
the pump drops telemetry stamped at or before the connection time, including
a packet held for retry. It also expires telemetry older than 1 s during an
active session. The budget remains four queue entries per pump. CONFIG_ACK
and PONG continue through the same queue. When the first telemetry since boot
expires, the boot flag moves to the first telemetry accepted for publication.

The S4 supervisor checks progress from audio capture, classification,
environment sensing and reporting every 100 ms. It logs which tasks have
reported and the largest observed gaps every 10 s. Idle classifier and report
tasks use bounded waits to show they can still run. A full outbound queue is
an expected reporting outcome during an outage. MQTT connection state does
not gate watchdog feeds.

`S4_WATCHDOG_TIMEOUT_MS` defaults to zero. Build and flash `NET=lwip MQTT=1`
with that default and run S4-U04 to measure healthy gaps under load, including
while the broker and Wi-Fi are unavailable. Include margin for the 100 ms
polling granularity and scheduling jitter. For bench validation, set the
measured timeout in `drv_watchdog.h` and rebuild the MQTT profile. At boot the
supervisor waits for recent progress from all four tasks before arming the
hardware, and each feed requires new progress from all four. Record S4-U05 and
S4-U06 before enabling a timeout in a production image.
