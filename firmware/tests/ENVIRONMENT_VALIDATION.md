# Environmental sensing validation

## Scope and architecture

The implementation baseline is the standalone Pico SDK 1.5.1 cooperative loop.
No FreeRTOS, queue, network producer, fusion adapter or wire schema was added.
No `mosaic_protocol.h` exists in this checkout. The PC prototypes are unchanged.
`sensor_data_t` now embeds the reusable `environment_record_t`; microphone
sampling, thresholds, fields and report code remain unchanged.

The active combined target uses DHT GP2, PIR GP16, UART1 TX GP8/RX GP9.
The existing `dht22_gp1` build target deliberately remains a GP1 standalone
hardware test, now sharing the integer/PIO implementation. Do not flash that
target expecting it to read the combined board's GP2 wiring.
The standalone `acd1100_test` retains its original blocking bring-up behavior;
the combined target uses the extracted non-blocking service in `sensors.c`.

## Numeric contract

| Field | Type | Unit/precision | Accepted range |
|---|---|---|---|
| temperature_x10 | int16_t | 0.1 C | -400..800 (-40.0..80.0 C) |
| humidity_x10 | uint16_t | 0.1 %RH | 0..1000 (0.0..100.0 %RH) |
| co2_ppm | uint16_t | 1 ppm | 0..65535 protocol encoding |
| motion | uint8_t | 0/1 activity | 0 no recent motion; 1 motion |
| timestamp_ms | uint32_t | 1 ms | modulo 2^32, wraps about every 49.7 days |

DHT22/AM2302 physical limits are checked before publishing. No readings are
clamped. A failed DHT transaction clears both DHT validity bits, retaining old
numeric values only for consumers explicitly inspecting historical values.
Other channels retain their own independent validity. ACD1100 frame header,
length, command and additive checksum are validated. Its two reserved bytes
participate in the checksum. No unverified physical CO2 range is invented;
confirm the exact module's range/error codes from its documentation before
using protocol-valid readings for safety decisions.

There are no averages, filters, occupancy scores or rate calculations in this
implementation. Thus there is no derived-value rounding or saturation.
Integer formatting is exact, including -0.1 and the full int16_t range; it uses
an int32_t magnitude, avoiding INT16_MIN negation overflow. Buffers of 8 bytes
hold the full representation including NUL. Smaller buffers truncate safely.
Checksums intentionally reduce modulo 256. Other sensor arithmetic does not
wrap. PIO clock divider calculation uses uint64_t multiplication and a Q8
integer divider, rounded down; at the default 125 MHz it is exact (62.5).
Do not change the system clock while this driver is configured.
Pulse widths have approximately 1 us resolution, with a few us acquisition
overhead covered by validation windows, not a sensor-value correction.

The record timestamp is refreshed each cooperative iteration; per-channel
sample times track the latest valid reading (DHT acquisition start time).
Unsigned elapsed subtraction is valid across timestamp wrap if service gaps
are less than one full wrap. Valid DHT/CO2/PIR readings become STALE after
6000/5000/1000 ms without refresh. Failures keep their specific error status.
WARMING UP is distinct from TIMEOUT and other failures. PIR GPIO cannot detect
a disconnected sensor: a pull-down reads LOW. PIR warm-up instability remains
a hardware consideration, not a claim of occupancy validity.

## PIO flow and ownership

One free PIO state machine and program slot are claimed on pio0, falling back
to pio1; one DMA channel is claimed without panicking on resource exhaustion.
Failure produces RESOURCE ERROR while the other sensors continue. Instances
are initialized once, own their resources for program lifetime, and must have
one caller. Initialize from single-threaded startup; program-space probing and
program installation are separate SDK calls, not a concurrent allocation API.
If DMA allocation fails, the already-claimed state machine is unclaimed.
No global IRQ disable, transaction lock, ISR or capture printing is
used. SDK resource claims use the SDK's normal short synchronization.

PIO at 2 MHz drives LOW for about 1.1 ms, then releases the bus (never drives
HIGH), synchronizes to the response, and measures alternating LOW/HIGH pulses
with two-cycle counting loops. DMA stores 82 uint32_t widths: response LOW/HIGH
and the 40 data-bit LOW/HIGH pairs. DMA lets capture finish during the existing
50 ms microphone window without overflowing the PIO FIFO.

Exact zero-based layout: entry 0 = response LOW, entry 1 = response HIGH;
entries 2+2*i and 3+2*i = data bit i LOW and HIGH, i=0..39, MSB first.
Entries 80/81 therefore describe the checksum's last bit. The host start LOW,
release-to-response delay and trailing sensor LOW are not entries in this array.

Task-context service checks DMA completion, disables the state machine,
aborts any unfinished DMA and releases DATA. A pending capture is aborted on
the first service call at/after 10 ms. This is a cooperative deadline, not a
10 ms interrupt: the unchanged microphone window can delay observation to
roughly 50 ms plus serial overhead. A missing transition may stall PIO, but
cannot stall the CPU loop. A completed capture is checked for legal response,
bit LOW and bit HIGH durations; ambiguous HIGH durations 41..49 us are rejected.
Then bytes are reconstructed MSB first, checksum checked, and raw tenths decoded.
The overall observed timeout does not prove individual response-start latency;
use a logic analyzer for protocol timing validation. No finite tolerance windows
can reject every possible corrupt waveform that happens to encode valid data.

Strict-review fixes: the polling DMA channel explicitly disables both of its
IRQ routes when claimed, clears its pending flags, and clears completion flags
after abort (including RP2040 E13 abort behavior). Other DMA channels/handlers
are untouched. Every completed/failed capture also clears the PIO FIFOs,
restarts internal state, releases DATA and returns the program counter to start.
Claims remain reserved across reads; they are not permanently active transfers.
The next attempt reconfigures the DMA address/count and restarts PIO. SDK DMA
abort waits for bus transfers to retire, not for a sensor transition. Hardware
failure of the DMA/bus itself is outside the sensor timeout guarantee.
Record timestamp uses service time; only a valid DHT sample timestamp uses
acquisition start, preventing a completion from backdating the record update.

Start is asynchronous. Call after at least 2 seconds of sensor power-up and
space attempts by at least 2 seconds; the supplied programs use 2500 ms.
Service regularly. No sensor completion is awaited in the caller. UART warm-up
is 120 seconds from initialization, with 2-second requests and 1-second reply
timeout. UART RX draining is bounded to 32 bytes, replies to 9 bytes. UART1 is
exclusively owned; the five-byte read request fits its empty 32-byte TX FIFO.
No calibration/configuration/reset command is transmitted.

## Compile and host validation

Run from repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Force firmware/build | Out-Null
gcc -std=c11 -Wall -Wextra -Werror -Ifirmware/environment firmware/environment/environment.c firmware/tests/environment_host_test.c -o firmware/build/environment_host_test.exe
& firmware/build/environment_host_test.exe

$sdk = 'C:/Program Files/Raspberry Pi/Pico SDK v1.5.1'
& "$sdk/cmake/bin/cmake.exe" -S firmware -B firmware/build/environment-validation -G Ninja "-DPICO_SDK_PATH=$sdk/pico-sdk" "-DPICO_TOOLCHAIN_PATH=$sdk/gcc-arm-none-eabi" "-DCMAKE_MAKE_PROGRAM=$sdk/ninja/ninja.exe" -DPICO_BOARD=pico_w
& "$sdk/cmake/bin/cmake.exe" --build firmware/build/environment-validation -j 4
```

Host coverage: positive/negative temperature, humidity, boundary and invalid
physical ranges, checksum failure without output overwrite, CO2 protocol and
checksum, synthetic valid/malformed pulse arrays, decimal formatting including
negative sub-degree and int16 boundaries, independent channel validity,
warm-up/timeout status, HIGH/LOW mapping, stale expiry and timestamp wrap.
Synthetic pulse tests exercise pure decoding only, not PIO or hardware timing.
No trend helper was introduced; rate/zero-divisor tests are inapplicable.
There was no environmental host suite before this change. Existing hardware
targets are preserved and compiled; compiling them is not executing their tests.
The ML `test_features.py` is an audio model/data utility, outside this change.

## Hardware verification still required

Compile/host results for this change: the host command above passed all
assertions; fresh SDK configure and the complete seven-target firmware build
passed, producing all existing UF2s without compiler warnings. `git diff --check`
passed. An exact source comparison also confirmed the three microphone
initialization/sampling/label functions were unchanged. Hardware tests below
have NOT been executed. No pre-existing environmental host tests existed to run.

Use `firmware/build/environment-validation/tests/mosaic_sensor_test.uf2`.
Provide a DATA pull-up to 3.3 V appropriate to your DHT module. Preserve the
CO2 level protection and common ground. Do not expose any Pico GPIO to 5 V.
Capture timestamped USB serial logs and, where indicated, a logic-analyzer trace.

1. Healthy startup: collect at least 130 seconds. DHT should show plausible
   tenths and OK while CO2 says WARMING UP; PIR must keep responding.
2. DHT timing: probe GP2; confirm ~1.1 ms open-drain start, sensor handshake,
   all 40 bits, >=2 s sampling spacing, and plausible values against a reference.
   Confirm interrupts/USB continue during acquisition. Test negative temperatures
   only with a suitable controlled setup or waveform generator.
3. Disconnect DHT DATA, then hold LOW/HIGH through suitable test wiring. Expect
   INVALID temperature/humidity and TIMEOUT, continuing timestamps, CO2 and PIR.
   Reconnect and verify automatic recovery on a later attempt.
4. With a protocol waveform generator, inject a legal-timing frame with a bad
   checksum: expect CHECKSUM ERROR; inject out-of-range values: OUT OF RANGE;
   malformed pulse widths: PROTOCOL ERROR or TIMEOUT. Log fault and recovery.
   Disconnect alone does not demonstrate checksum handling.
5. After PIR stabilization, move then remain still. Expect MOTION then NO RECENT
   MOTION following the module's hold time, never an empty-classroom assertion.
6. After CO2 warm-up, capture integer ppm with OK. Disconnect RX and wait for a
   request timeout; expect TIMEOUT while DHT/PIR continue. Reconnect and confirm
   recovery. Using a UART fixture, test bad checksum/header and partial replies.
7. Run all sensors together for >=10 minutes, including simultaneous DHT/CO2
   disconnections. Collect successive report times, status/validity transitions,
   plausible sensor values and recovery. Normal fully valid bitmask is 0x0F;
   DHT failure with healthy CO2/PIR is 0x0C; CO2 failure with healthy DHT/PIR is
   0x0B. Confirm no loop hang and nominal ~2-second reports (allow cooperative
   and USB timing jitter). Microphone output should retain its original behavior.
8. Optional GP1 legacy test: flash `dht22_gp1.uf2` with DATA wired to GP1; verify
   it uses the same status/format behavior without changing combined GP2 wiring.

## Audit and review

No floating-point types, operations, conversions or formatting remain in
`firmware/environment/`, combined environmental code, legacy DHT test, standalone
CO2 test or PIR test. `floor` in explanatory prose denotes integer divider
rounding only. SDK-generated PIO headers expose generic SDK helpers and SDK
build definitions may mention float support; these are not application processing.
Audio DSP files and ML/PC prototype floating-point code remain out of scope.
The unrelated untracked root microphone file was not read, edited or staged
during this implementation. No commit or push is performed.
