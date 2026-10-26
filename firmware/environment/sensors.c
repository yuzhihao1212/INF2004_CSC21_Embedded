#include "sensors.h"
#include "pico/stdlib.h"

static uint64_t now_ms(void) { return time_us_64() / 1000; }
void environment_pir_init(unsigned pin) {
    gpio_init(pin); gpio_set_dir(pin, GPIO_IN); gpio_pull_down(pin);
}
void environment_pir_read(environment_record_t *r, unsigned pin) {
    environment_apply_pir(r, gpio_get(pin), (uint32_t)now_ms());
}
void acd1100_init(acd1100_t *s, uart_inst_t *uart, unsigned tx, unsigned rx) {
    *s = (acd1100_t){.uart = uart, .warmup_end_ms = now_ms() + 120000};
    s->next_request_ms = s->warmup_end_ms;
    uart_init(uart, 1200);
    gpio_set_function(tx, GPIO_FUNC_UART); gpio_set_function(rx, GPIO_FUNC_UART);
    uart_set_hw_flow(uart, false, false);
    uart_set_format(uart, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(uart, true);
}
void acd1100_service(acd1100_t *s, environment_record_t *r) {
    uint64_t now = now_ms();
    if (now < s->warmup_end_ms) {
        environment_apply_co2(r, SENSOR_WARMING_UP, 0, (uint32_t)now); return;
    }
    if (s->waiting) {
        while (s->received < sizeof(s->response) && uart_is_readable(s->uart))
            s->response[s->received++] = (uint8_t)uart_getc(s->uart);
        if (s->received == sizeof(s->response)) {
            uint16_t ppm = 0;
            sensor_status_t status = environment_decode_co2(s->response, &ppm);
            environment_apply_co2(r, status, ppm, (uint32_t)now);
            s->waiting = false;
        } else if (now >= s->deadline_ms) {
            environment_apply_co2(r, SENSOR_TIMEOUT, 0, (uint32_t)now);
            s->waiting = false;
        }
        return;
    }
    if (now < s->next_request_ms) return;
    s->next_request_ms = now + 2000; s->received = 0;
    for (unsigned i = 0; i < 32 && uart_is_readable(s->uart); ++i) (void)uart_getc(s->uart);
    if (uart_is_readable(s->uart)) {
        environment_apply_co2(r, SENSOR_PROTOCOL_ERROR, 0, (uint32_t)now); return;
    }
    /* Preserve FE A6 read-only protocol. Five bytes fit in the 32-byte TX
     * FIFO. Check that it is empty first so write_blocking cannot wait for
     * wire transmission if another caller violated exclusive UART ownership. */
    if (uart_get_hw(s->uart)->fr & UART_UARTFR_BUSY_BITS) {
        environment_apply_co2(r, SENSOR_PROTOCOL_ERROR, 0, (uint32_t)now); return;
    }
    static const uint8_t request[] = {0xfe, 0xa6, 0, 1, 0xa7};
    uart_write_blocking(s->uart, request, sizeof(request));
    s->deadline_ms = now_ms() + 1000; s->waiting = true;
}
