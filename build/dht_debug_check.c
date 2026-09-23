
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned int uint;
typedef struct { float temperature,humidity; } sensor_data_t;
#define DHT_PIN 1
#define GPIO_OUT 1
#define GPIO_IN 0
static uint32_t tick, released;
static bool irq_off;
static int fault;
static uint8_t frame[5];
static uint32_t time_us_32(void) { return tick++; }
static void busy_wait_us_32(uint32_t n) { tick+=n; }
static void gpio_put(int p,int v) {(void)p;(void)v;}
static void gpio_set_dir(int p,int d) {(void)p;if(d==GPIO_IN)released=tick;}
static void gpio_pull_up(int p) {(void)p;}
static uint32_t save_and_disable_interrupts(void) {irq_off=true;return 1;}
static void restore_interrupts(uint32_t n) {(void)n;irq_off=false;}
static bool gpio_get(int p) {
 (void)p; uint32_t t=tick-released;
 if(fault==1)return false;
 if(fault==2)return true;
 if(t<30)return true;t-=30;
 if(fault==3)return false;
 if(t<80)return false;t-=80;
 if(fault==4)return true;
 if(t<80)return true;t-=80;
 for(unsigned i=0;i<40;i++) {
   if(fault==5 && i==12)return false;
   if(t<50)return false;t-=50;
   if(fault==6 && i==12)return true;
   unsigned duration=(frame[i/8] & (1u<<(7-i%8)))?70:26;
   if(t<duration)return true;t-=duration;
 }
 return t>=50;
}
static int debug_printf(const char *fmt,...) {
 assert(!irq_off);va_list args;va_start(args,fmt);int n=vprintf(fmt,args);va_end(args);return n;
}
#define printf debug_printf
static const char *dht_error = "not read yet";

// Every wait has a microsecond deadline. Unsigned subtraction also works
// across the 32-bit timer wrap. Called only with interrupts disabled.
static bool dht_wait_level(bool level, uint32_t timeout_us) {
    uint32_t start = time_us_32();
    while (gpio_get(DHT_PIN) != level) {
        if ((uint32_t)(time_us_32() - start) >= timeout_us) return false;
    }
    return true;
}

static bool read_dht22(sensor_data_t *data) {
    uint8_t bytes[5] = {0};
    uint bits = 0;
    const char *error = NULL;
    bool reading_bits = false;

    // DHT22/AM2302 start: LOW for at least 800 us (about 1 ms typical).
    // Preload LOW before enabling output; never actively drive the bus HIGH.
    gpio_put(DHT_PIN, 0);
    gpio_set_dir(DHT_PIN, GPIO_OUT);
    busy_wait_us_32(1100);

    uint32_t irq_state = save_and_disable_interrupts();
    gpio_pull_up(DHT_PIN);
    gpio_set_dir(DHT_PIN, GPIO_IN);

    // Synchronise to actual levels rather than assuming the first observed
    // transition's index. The bus first rises through its pull-up, then the
    // sensor responds with about 80 us LOW followed by about 80 us HIGH.
    if (!dht_wait_level(true, 40)) {
        error = "DATA did not rise after release (pull-up / stuck LOW)";
    } else if (!dht_wait_level(false, 250)) {
        error = "initial sensor response LOW timeout";
    } else if (!dht_wait_level(true, 120)) {
        error = "initial response HIGH timeout (response stayed LOW)";
    } else if (!dht_wait_level(false, 120)) {
        error = "initial response HIGH did not end / first bit LOW timeout";
    } else {
        reading_bits = true;
        for (bits = 0; bits < 40; ++bits) {
            // Each bit starts LOW (~50 us); measure only its HIGH pulse.
            if (!dht_wait_level(true, 100)) {
                error = "data-bit LOW did not end / HIGH timeout";
                break;
            }
            uint32_t high_start = time_us_32();
            if (!dht_wait_level(false, 120)) {
                error = "data-bit HIGH did not end / LOW timeout";
                break;
            }
            uint32_t high_us = time_us_32() - high_start;
            // Zero is ~26 us HIGH, one is ~70 us HIGH. 50 us separates them.
            bytes[bits / 8] = (uint8_t)((bytes[bits / 8] << 1) |
                                      (high_us > 50 ? 1 : 0));
        }
    }
    restore_interrupts(irq_state);
    // GPIO stays released with its pull-up enabled on both success and error.
    // All diagnostics occur AFTER capture and interrupt restoration.
    if (error) {
        dht_error = error;
        printf("DHT22 ERROR: %s\n", error);
        if (reading_bits) {
            printf("DHT22: failed at data bit %u (1-based)\n", bits + 1);
        }
        printf("DHT22: fewer than 40 bits received (%u/40)\n", bits);
        return false;
    }

    printf("DHT raw: %02X %02X %02X %02X %02X\n",
           (unsigned int)bytes[0], (unsigned int)bytes[1],
           (unsigned int)bytes[2], (unsigned int)bytes[3], (unsigned int)bytes[4]);
    uint8_t checksum = (uint8_t)(bytes[0] + bytes[1] + bytes[2] + bytes[3]);
    if (checksum != bytes[4]) {
        dht_error = "checksum validation failed";
        printf("DHT22 ERROR: checksum calculated=%02X received=%02X\n",
               (unsigned int)checksum, (unsigned int)bytes[4]);
        return false;
    }
    data->humidity = ((bytes[0] << 8) | bytes[1]) / 10.0f;
    data->temperature = (((bytes[2] & 0x7f) << 8) | bytes[3]) / 10.0f;
    // DHT22 temperature uses sign/magnitude, not two's complement.
    if (bytes[2] & 0x80) data->temperature = -data->temperature;
    dht_error = NULL;
    return true;
}


int main(void) {
 sensor_data_t d={0};
 uint8_t positive[]={0x02,0x65,0x00,0xf6,0x5d};memcpy(frame,positive,5);
 assert(read_dht22(&d)); assert(d.humidity>61.29f && d.humidity<61.31f);assert(d.temperature>24.59f && d.temperature<24.61f);
 frame[2]=0x80;frame[3]=0x7b;frame[4]=(uint8_t)(frame[0]+frame[1]+frame[2]+frame[3]);
 assert(read_dht22(&d));assert(d.temperature < -12.29f && d.temperature > -12.31f);
 frame[4]^=1;assert(!read_dht22(&d));assert(strstr(dht_error,"checksum"));frame[4]^=1;
 for(fault=1;fault<=6;fault++) {uint32_t start=tick;assert(!read_dht22(&d));assert(!irq_off);assert(tick-start<10000);}
 puts("PASS: valid data, negative temperature, checksum, release/response/bit timeouts; diagnostics only after interrupts restored. Other sensor functions and main unchanged.");
}
