#ifndef MOSAIC_ENVIRONMENT_H
#define MOSAIC_ENVIRONMENT_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ENV_TEMP_VALID (1u << 0)
#define ENV_RH_VALID   (1u << 1)
#define ENV_CO2_VALID  (1u << 2)
#define ENV_PIR_VALID  (1u << 3)
#define ENV_DHT_VALID  (ENV_TEMP_VALID | ENV_RH_VALID)

typedef enum {
    SENSOR_STALE, SENSOR_OK, SENSOR_WARMING_UP, SENSOR_TIMEOUT,
    SENSOR_CHECKSUM_ERROR, SENSOR_OUT_OF_RANGE, SENSOR_PROTOCOL_ERROR,
    SENSOR_RESOURCE_ERROR
} sensor_status_t;

/* Numeric contract:
 * temperature_x10: signed 0.1 C/LSB, DHT22 valid -400..800.
 * humidity_x10: unsigned 0.1 %RH/LSB, valid 0..1000.
 * co2_ppm: unsigned 1 ppm/LSB, protocol encoding 0..65535. No narrower
 * physical range is assumed without a verified module specification.
 * motion: 0/1, activity only; LOW is not evidence of an empty classroom.
 * timestamp_ms and sample times: modulo-2^32 milliseconds. Expiry assumes
 * sample ages and future offsets are less than 2^31 ms (half a wrap), so
 * slightly future samples remain fresh and forward rollover still works.
 * Raw values are exact: no rounding, saturation, or physical-value clamping.
 * Failed reads preserve last values but clear the corresponding validity bits.
 * Consumers MUST check validity; status explains invalidity, including warm-up.
 * This is an in-memory record, not a packed wire format.
 */
typedef struct {
    uint32_t timestamp_ms;
    int16_t temperature_x10;
    uint16_t humidity_x10;
    uint16_t co2_ppm;
    uint8_t motion;
    uint8_t validity_flags;
    sensor_status_t dht_status, co2_status, pir_status;
    uint32_t dht_sample_ms, co2_sample_ms, pir_sample_ms;
} environment_record_t;

const char *environment_status_name(sensor_status_t status);
sensor_status_t environment_decode_dht(const uint8_t bytes[5],
                                     int16_t *temperature_x10, uint16_t *humidity_x10);
/* 82 measured pulses, in us:
 * [0] sensor response LOW; [1] sensor response HIGH;
 * [2 + 2*i] data bit i LOW; [3 + 2*i] data bit i HIGH, i=0..39.
 * Bit 0 is byte 0's MSB; bit 39 is checksum byte's LSB.
 * Host start LOW, release-to-response delay and trailing LOW are excluded. */
sensor_status_t environment_decode_dht_pulses(const uint32_t pulses[82], uint8_t bytes[5]);
sensor_status_t environment_decode_co2(const uint8_t frame[9], uint16_t *ppm);
void environment_apply_dht(environment_record_t *r, sensor_status_t status,
                           int16_t temperature_x10, uint16_t humidity_x10, uint32_t now);
void environment_apply_co2(environment_record_t *r, sensor_status_t status,
                           uint16_t ppm, uint32_t now);
void environment_apply_pir(environment_record_t *r, bool high, uint32_t now);
void environment_expire(environment_record_t *r, uint32_t now);
/* Exact decimal display. int32_t magnitude handles INT16_MIN; buffer >= 8. */
void environment_format_x10(char *out, size_t size, int16_t value);
#endif
