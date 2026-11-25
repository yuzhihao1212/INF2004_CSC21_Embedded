/*
 *	mqtt_utk.h
 *	MQTT client wiring for micro T-Kernel (RP2040, NO_SYS=1)
 */

#ifndef MQTT_UTK_H
#define MQTT_UTK_H

/* Call from cyw43_utk_task before lwIP timeouts. Closes the old MQTT
 * session on Wi-Fi loss or schedules a broker connection when Wi-Fi is up. */
void mqtt_utk_poll(int wifi_up);

/* Call only from cyw43_utk_task(). Returns 1 while connected to the broker. */
int mqtt_utk_is_connected(void);

#endif /* MQTT_UTK_H */
