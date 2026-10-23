/* Legacy GP1 standalone test. Combined MOSAIC allocation remains GP2. */
#include <stdio.h>
#include "pico/stdlib.h"
#include "dht22.h"

int main(void) {
    stdio_init_all();
    dht22_t dht;
    environment_record_t record = {0};
    bool ready = dht22_init(&dht, 1);
    sleep_ms(2000);
    printf("Legacy DHT22 test: GP1 (combined MOSAIC uses GP2)\n");
    if (!ready) printf("DHT22: RESOURCE ERROR\n");
    uint64_t next_read = 0;
    while (true) {
        uint64_t now = time_us_64() / 1000;
        if (ready && !dht.active && now >= next_read) {
            (void)dht22_start(&dht); next_read = now + 2500;
        }
        if (dht22_service(&dht, &record)) {
            if ((record.validity_flags & ENV_DHT_VALID) == ENV_DHT_VALID) {
                char t[8], h[8];
                environment_format_x10(t, sizeof(t), record.temperature_x10);
                environment_format_x10(h, sizeof(h), (int16_t)record.humidity_x10);
                printf("Temperature: %s C\nHumidity: %s %%\n", t, h);
            }
            printf("DHT22: %s\n", environment_status_name(record.dht_status));
        }
        sleep_ms(1);
    }
}
