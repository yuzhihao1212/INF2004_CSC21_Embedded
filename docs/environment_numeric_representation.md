# S3 environmental numeric representation

This describes the μT-Kernel node implementation in `node/app_program/subsystem3/` and its S5 interface, not measured sensor accuracy.

| Quantity | In-memory type | Encoded range and scale | Accepted values and resolution |
|---|---|---|---|
| Temperature | `int16_t` | signed tenths of °C, representable −3276.8..3276.7 °C | DHT data accepted −40.0..80.0 °C (−400..800); 0.1 °C per count |
| Relative humidity | `uint16_t` | tenths of %RH, representable 0..6553.5 %RH | accepted 0.0..100.0 %RH (0..1000); 0.1 %RH per count |
| CO2 | `uint16_t` | unsigned ppm, 0..65535 | 1 ppm per count; no narrower instrument operating range is asserted |
| PIR | `uint8_t` | 0 or 1 | 1 GPIO sample of motion state; not occupancy or a health check |
| Times | `uint32_t` | monotonic milliseconds modulo 2^32 | 1 ms unit; actual service cadence is limited by the kernel tick and scheduling |

Resolution is the encoded increment, not sensor accuracy or comparison precision. B4's acceptance targets are ±1 °C and ±5 %RH relative to the chosen reference; they are not results. The CO2 range is an encoding range, not a claim of calibrated accuracy. Document the reference instrument, its resolution, accuracy and calibration when measuring.

DHT humidity bytes form an unsigned magnitude. Temperature's sign bit and magnitude are decoded through `int32_t`, checked against the accepted range, then narrowed to `int16_t`. No decimal conversion, float, rounding or saturation occurs in acquisition; representable sensor tenths pass through unchanged. DHT checksum uses a modulo-256 byte sum; the bounded byte sum fits in `int`. CO2 big-endian bytes directly form a 16-bit ppm value; its checksum is also modulo 256. Invalid checksums, malformed pulses/frames and out-of-range DHT values are rejected, not clamped. Formatting uses an `int32_t` magnitude so `INT16_MIN` is safe.

PIR totals are unsigned 32-bit. S3 stops increasing the current batch at `UINT32_MAX` and counts dropped samples; S5 saturates accumulated counts, clamps active to samples and computes `100ull * active / samples`, truncating toward zero. It reports PIR valid only if the interval had samples. `LOW` can also mean an unplugged, pulled-down input.

S3 record mask: bit 0 `ENV_TEMP_VALID`, bit 1 `ENV_RH_VALID`, bit 2 `ENV_CO2_VALID`, bit 3 `ENV_PIR_VALID`. Both DHT bits are set together. S5/wire mask is different: bit 0 combined temperature/humidity, bit 1 CO2, bit 2 CO2 warm-up, bit 3 PIR. Do not interpret the diagnostic S3 mask as a packet mask. CO2 warm-up in the wire mask is a status, not a valid CO2 reading.

Failed reads retain the previous numeric value but clear that sensor's valid bits and update its status. Values are unusable unless their validity bits are set. Expiry clears valid bits after age exceeds 6000 ms for DHT, 5000 ms for CO2 and 1000 ms for PIR. CO2 starts with a 120 s warm-up, when no CO2 value is valid. S3 posts its current state periodically; S5 uses a separate 6000 ms age from the last successful post, zeroes invalid wire fields and uses its own 64-bit operating time. Posting failures can delay delivery of invalidation. Intervals longer than S3's freshness limits cause honest invalid gaps.

Unsigned subtraction handles 32-bit millisecond rollover (~49.71 days). Elapsed/expiry logic interprets an age in the upper half of the range as a future sample; all compared ages and future offsets must be less than 2^31 ms (~24.85 days). It is not a substitute for a wider clock for arbitrarily old records. Diagnostic counters saturate at `UINT32_MAX`; progress wraps modulo 2^32.
