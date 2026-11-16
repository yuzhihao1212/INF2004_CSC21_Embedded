# Subsystem 4: MQTT handoff and node health

In the shared MQTT service, subscribe to `s4_mqtt_config_topic()` at QoS 1
after each successful connection. Pass the complete inbound message and its
original topic to `s4_mqtt_receive()`. This includes both CONFIG and PING.
Once connected, drain `s4_mqtt_take_outbound()` into an S5_TX_MAX-byte buffer
and publish each returned datagram on `s4_mqtt_telemetry_topic()` at QoS 0
without retain. Configure the offline last will on `s4_mqtt_status_topic()`
and publish the online status after connection. The handoff never blocks;
check return values and count any dropped messages. Subsystem 5 handles
CONFIG_ACK and PONG. The MQTT service still needs these calls wired in.

Health reports track loop progress separately from network connection state.
The future watchdog supervisor should call `s4_health_take(required)` and
feed only on E_OK, after each task in the selected build has reported actual
progress using `s4_health_mark()`. No hardware watchdog is armed by this
change. The old template monitor remains available for the example
subsystems that still reference it.

First integration check once the network hook is connected: build with
`NET=lwip MQTT=1`, flash a Pico, and verify the dashboard sees telemetry and
the gateway receives an OK CONFIG_ACK from the node.
