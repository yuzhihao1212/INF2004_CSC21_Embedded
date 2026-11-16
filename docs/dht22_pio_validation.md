# DHT22 PIO/DMA audit and validation

Reviewed on 13 November 2026 against the current checkout, base `3501efe`, on
`feat/dht22-pio-validation`. This is a source audit, host regression suite and
hardware evidence collector. **No Pico was flashed and no hardware results were
collected.** Builds cannot establish sensor success rate or physical timing.

## Audit conclusions

### Confirmed defects and evidence gaps

No confirmed correctness defect was found in the production DHT22 driver that
justifies changing its assembly, timing, FIFO format, thresholds or timeout.
The actionable gaps were limited decoding coverage and the absence of a dedicated
GP2 acquisition statistics target. Those gaps are addressed here.

The combined `mosaic_sensor_test` samples its microphone in a 50 ms foreground
window. Its DHT completion observation, including a nominal 10 ms timeout, can
therefore arrive tens of milliseconds late. This is existing caller scheduling,
not PIO timing. The new target sleeps 100 us between nonblocking service calls
and reports observed latency explicitly. It does not change that combined test.

### Already correct

- DATA is only driven LOW; HIGH is an input with pull-up. No push-pull HIGH is
  issued. The initial latch is set LOW before output direction is enabled.
- The start and response handshake occur inside PIO. The first captured pair
  is sensor response LOW/HIGH, followed by forty LOW/HIGH bit pairs.
- PIO holds edge timing independently of ARM scheduling. DMA drains the RX FIFO
  directly into exactly 82 aligned `uint32_t` slots (328 bytes).
- Startup claims an unused SM and unused DMA channel without stealing resources.
  It tests program space, tries both PIO blocks, and releases the SM if DMA is
  unavailable. Claims/program memory are retained for the instance lifetime.
- Acquisition starts asynchronously. Incomplete buffers are never decoded.
  Cleanup disables the SM, aborts this DMA channel, acknowledges only its IRQ
  bits, clears RX FIFO, restarts the SM, releases DATA, and restores the entry PC.
- The polling channel disables both of its DMA interrupt routes, including stale
  pending bits from earlier ownership. It installs no handler or global mask.
- Decoding rejects malformed timings, checksum failures and invalid physical
  ranges. Failed reads retain last good numbers/sample time and clear DHT validity.
- Divider arithmetic, pulse handling, measurements and timestamps use integers.
  The current unsigned-age expiry logic also rejects future-dated samples; it is
  unchanged and now has an explicit host regression.

### Possible hardware and integration risks

- An external pull-up to **3.3 V**, short wiring and common ground are necessary
  for reliable edges. The internal pull-up is not evidence of sufficient rise
  time. A module with a pull-up to 5 V requires appropriate level protection.
- Noise, excessive rise time, or DMA starvation can distort counts or lose edges.
  `push block` preserves words but stalls measurement when the eight-word RX
  FIFO fills. Sustained DMA latency must be checked under actual audio/Wi-Fi load.
- An unplugged or stuck line stalls a PIO wait/counter until CPU service cancels
  it. Timeout is observed at the first service call at/after 10,000 us, not an
  autonomous PIO deadline. A long scheduling gap delays cleanup. A buffer already
  complete at a late service call is decoded even if that call is after 10 ms.
- `BUSY == false` is the production completion check; it assumes ordinary DMA
  operation. DMA/bus faults, unexpected reconfiguration or resource misuse are
  outside the sensor timeout guarantee and are not detected by this collector.
- PIO program space is shared with other users, including Pico W networking.
  One instance needs 20 of a block's 32 instruction slots and one of its four SMs.
  Initialization is single-threaded, once only; the can-add/claim/add sequence is
  not a general concurrent allocator. Resource exhaustion must remain visible.
- The standalone collector does not run audio, CO2, PIR or networking. Successful
  standalone capture does not demonstrate concurrent operation or CPU utilization.

### Optional optimizations intentionally avoided

No bottleneck evidence supports replacing 82 pulse words with a bit-packing
architecture, allocating a new task, installing a DHT IRQ, altering clock rate,
tightening windows or changing timeout precedence. At one attempt per 2.5 s,
the programmed capture payload averages only 131.2 bytes/s (3280/25 bytes/s).
The buffer costs 328 bytes. That is a design calculation, not measured bus/CPU
load. PIO may produce an unused trailing LOW word before service stops it.

There is consequently no proposed production-driver change requiring a
before/after performance claim. Any future timing change must retain baseline
USB logs and GP2 traces, repeat the same waveform/fault/load tests, and document
old behavior, the defect, the implementation, expected benefit and new risks.

## Architecture and responsibilities

```text
ARM caller: >=2 s warm-up, >=2 s between starts
    |
    | dht22_start(): clear/restart, configure 82-word DMA, enable SM
    v
GP2 <--> PIO SM at nominal 2 MHz
          LOW start -> release -> response sync -> alternating pulse counters
                                      |
                               RX FIFO, joined: 8 words
                                      |
                          RX DREQ -> owned DMA channel
                                      |
                            dht22_t.pulses[82] in SRAM
                                      |
ARM dht22_service(): poll completion / 10 ms elapsed timeout
    stop SM -> abort/ack DMA -> clear/release/restart
    complete only -> timing decode -> 5 bytes -> checksum/range decode
    environment_apply_dht() -> status + raw fixed-point values + validity
                                      |
production: snapshot -> existing telemetry / RTOS consumers
validation target: integer statistics -> USB AFTER acquisition
```

PIO generates the handshake and counts edges. DMA moves words; it does not
interpret them. ARM owns scheduling, cancellation, byte reconstruction,
checksum/range checking and validity. USB prints are outside acquisition in the
new collector; existing SDK USB interrupts may still run during acquisition.

## Assembly and exact cycle accounting

`firmware/environment/dht22.pio` contains 20 instructions. Normal instructions
take one SM clock; `[n]` adds `n` clocks. `jmp x--` / `jmp y--` test the value
before decrement, and decrement on the final untaken branch too. Hardware wrap
adds no branch instruction. See the
[RP2040 PIO instruction reference, sections 3.2 and 3.4](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf).

1. `set pins, 0` sets the output latch LOW while the pad is still input.
2. `set pindirs, 1` starts the open-drain LOW; `set x, 31` initializes 32
   outer iterations.
3. Each outer iteration executes `set y, 1` (one cycle), then
   `jmp y-- start_inner [31]` twice (32 cycles each), then
   `jmp x-- start_outer [3]` (four cycles, including the final untaken branch).
4. `set pindirs, 0` releases the line. Between the output-enable and release
   instruction edges the LOW duration is:

   ```text
   1 (output-enable instruction) + 1 (set x)
       + 32 * (1 + 2 * 32 + 4) = 2210 SM cycles
   2210 / 2 cycles per microsecond = 1105 us
   ```

   The preceding `set pins, 0` is outside that LOW interval. Delays on an
   untaken jump still count. Pad propagation and clock accuracy require a trace.
5. `wait 1 pin 0` waits for release HIGH, then `wait 0 pin 0` synchronizes to
   response LOW. Input mapping makes pin 0 relative to GP2. A stuck LOW waits
   on the first instruction; a stuck HIGH waits on the second.
6. `mov x, ~null` starts X at `UINT32_MAX`. LOW repeats `jmp pin low_done`
   and `jmp x-- low_loop`: two cycles per decrement while LOW. On HIGH,
   `mov isr, ~x` yields the number of decrements, and `push block` emits it.
7. HIGH uses `jmp pin high_count` then `jmp x-- high_loop`, again two cycles
   per decrement. On LOW, `jmp high_done`, `mov isr, ~x`, `push block` emit
   its count. Wrap repeats LOW/HIGH measurement, not the start handshake.

The divider is computed as
`divider_x256 = floor((uint64_t)clk_sys_hz * 256 / 2000000)` and programmed as
integer and fractional Q8 parts. At the standard 125 MHz system clock it is
exactly 62 + 128/256, so the nominal SM period is 0.5 us. Two clocks per
decrement give **1 us per count**; the data type does not encode half-us ticks.
For another system clock, Q8 truncation can make the SM slightly faster; record
`clk_sys_hz` and calculate the actual divider before comparing physical timings.

Counts are not calibrated pad pulse widths. With no FIFO stall, the first HIGH
check occurs four SM cycles after the LOW loop detects a rising edge. The next
LOW check occurs five cycles after the HIGH loop detects a falling edge. The
first response LOW also includes WAIT/setup latency. These overheads shorten
counts by a few us, with sampling phase adding quantization. No universal fixed
offset should be added. The existing tolerant windows account for this; compare
measured counts with an external trace before proposing threshold changes.

## Captured words and decoder contract

All indices below refer to `uint32_t` pulse counts, nominally in us:

| Index | Meaning | Accepted count |
| --- | --- | --- |
| 0 | Sensor response LOW | 60..100 inclusive |
| 1 | Sensor response HIGH | 60..100 inclusive |
| 2 + 2*i | Data bit i LOW, i=0..39 | 35..70 inclusive |
| 3 + 2*i | Data bit i HIGH | 15..40 = 0; 50..90 = 1 |

HIGH 41..49 is always a protocol error, including both endpoints. Other widths
outside these windows are also protocol errors. These are **decoder acceptance
windows**, not sensor manufacturer tolerances. Host start LOW, release delay
and trailing LOW are excluded. The last data HIGH is emitted when the sensor
pulls LOW after the last bit; a missing last falling edge causes incomplete DMA.

Bits are MSB first: humidity high byte, humidity low byte, temperature high byte,
temperature low byte, checksum. `environment_decode_dht_pulses()` checks timing
and packs bytes only. Its output may be partially overwritten on failure and
must be ignored unless it returns `SENSOR_OK`.
`environment_decode_dht()` then verifies the sum modulo 256, sign-magnitude
temperature and physical range; numeric output pointers are unchanged on failure.

The [Aosong AM2302 product manual, sections 7.3 and 7.4](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/908/DHT22_5F00_detailed_5F00_Datasheet.pdf)
specifies at least 2 s power-up and read spacing, an open-drain start, nominal
80 us response phases and nominal data timing of 50 us LOW, 26 us zero HIGH or
70 us one HIGH. This explains the two data clusters; verify the actual module.

## DMA, cleanup, audio and scheduling

The driver uses `DMA_SIZE_32`, a fixed read address `pio->rxf[sm]`, incrementing
SRAM writes, transfer count 82, and `pio_get_dreq(pio, sm, false)` (RX). RX FIFO
joining provides eight words; TX is unused. DMA is armed before the SM starts.
Its default configuration chains to itself (no other channel is triggered).

On completion or observed timeout, the SM is disabled before DMA abort, so it
cannot issue further pushes. SDK 1.5.1 `dma_channel_abort()` waits on channel
BUSY, allowing in-flight bus operations to retire. Both DHT DMA IRQ routes stay
disabled and both pending bits are acknowledged after abort. This follows the
[SDK RP2040-E13 guidance](https://www.raspberrypi.com/documentation/pico-sdk/hardware.html#group_hardware_dma)
for spurious completion IRQs during abort. It does not mask unrelated channels.
No buffer reads occur while DMA is active. An incomplete array can contain an
old suffix, so neither production decode nor validation ranges inspect it.

Audio claims a different channel paced by ADC DREQ, with 16-bit transfers and
its existing exclusive DMA_IRQ_0 handler. DHT never replaces that handler or
enables its own IRQ route. PIO SM/program and DMA claims remain reserved across
attempts; they are not unclaimed on timeout. Reinitialize neither live driver.

The normal node cooperatively services at approximately 1 ms sleep cadence;
the RTOS environment task requests a 2 ms period. Actual gaps include other
work and interrupts. Only that task owns the sensor drivers, and snapshot locks
are outside driver calls. SMP/audio hooks, network task, watchdog feed gate and
their interfaces are unchanged. A two-core build without
`MOSAIC_NODE_AUDIO_SOURCES` verifies SMP compilation, not a running audio task.

## Numeric types and statistics

- Pulse buffers: `uint32_t[82]`, 328 bytes, nominal us/count. Five decoded bytes
  are `uint8_t[5]`; checksum truncation to `uint8_t` is intentional modulo 256.
- Temperature: `int16_t`, 0.1 C/LSB, accepted -400..800. Humidity: `uint16_t`,
  0.1 %RH/LSB, accepted 0..1000. Temperature decoding uses `int32_t` magnitude
  before narrowing. No smoothing, saturation or replacement of raw values.
- Driver start, collector deadlines and observed durations: `uint64_t` us since
  boot. Duration minimum/maximum/sum/average: `uint64_t`; average floors the sum
  divided by count. No divide is performed for an empty group (printed `NA`).
- Attempts, status counts and pulse range counts/min/max: `uint32_t`. The CMake
  attempt range is 1..1,000,000; at most 40,000,000 data LOWs/HIGHs fit in each
  range count. Defaults are 100 attempts, 2,500,000 us spacing, 100 us service sleep.
- `valid_rate_x100_percent`: integer hundredths of a percent, e.g. 9900 means
  99.00%. The numerator is widened to `uint64_t` before multiplication.
- Record and sample times: `uint32_t` modulo milliseconds. Record time uses
  service time; a valid DHT sample is dated from start. Unsigned expiry and
  failure semantics are preserved, including rollover/future-date protection.

The collector reports total attempts, starts, valid results, complete buffers,
OK/timeout/checksum/protocol/other counts, and separate initialization/start
failures. OUT_OF_RANGE is counted under `other`; the per-attempt raw status
retains its exact value. An initialization failure reports zero attempts rather
than inventing 100 sensor failures. A rejected start is counted in `other` and
`start_errors`, without rewriting sensor status.

Observed duration runs from the driver's `started_us` timestamp until service
returns, including enable overhead, service polling delay, cleanup and decode.
It is **not exact DMA-completion time, wire duration or CPU busy time**. Aggregate
durations are separate for all starts, complete buffers, valid frames and
timeouts. Pulse ranges for complete buffers include malformed/checksum/range
frames; zero/one HIGH ranges include valid frames only. Per-attempt pulse lines
allow contaminated fault runs to be separated. Empty ranges print `NA`.
USB logging occurs after acquisition and may extend the next interval; the
collector never catches up by starting earlier than its actual previous start
plus 2.5 s. SDK USB servicing/interrupts remain possible during acquisition.

## Reproduce software validation

Run from repository root in PowerShell, using fresh ignored build directories:

```powershell
New-Item -ItemType Directory -Force firmware/build/dht22-validation-host | Out-Null
gcc -std=c11 -Wall -Wextra -Werror -Ifirmware/environment firmware/environment/environment.c firmware/tests/environment_host_test.c -o firmware/build/dht22-validation-host/environment_host_test.exe
& firmware/build/dht22-validation-host/environment_host_test.exe
Push-Location pc
python -X utf8 -m unittest discover -s tests -v
Pop-Location

$sdk = 'C:/Program Files/Raspberry Pi/Pico SDK v1.5.1'
$cmake = "$sdk/cmake/bin/cmake.exe"
$base = @('-G', 'Ninja', "-DPICO_SDK_PATH=$sdk/pico-sdk", "-DPICO_TOOLCHAIN_PATH=$sdk/gcc-arm-none-eabi", "-DCMAKE_MAKE_PROGRAM=$sdk/ninja/ninja.exe", '-DPICO_BOARD=pico_w', '-DCMAKE_OBJECT_PATH_MAX=200')
& $cmake -S firmware -B firmware/build/dht22-pio-validation @base -DMOSAIC_BUILD_RTOS=OFF
& $cmake --build firmware/build/dht22-pio-validation -j 4
& $cmake --build firmware/build/dht22-pio-validation --target dht22_pio_validation -j 4

# Set this to the pinned FreeRTOS-Kernel V11.2.0 checkout on your machine:
$kernel = 'C:/path/to/FreeRTOS-Kernel'
# Expected revision: 0adc196d4bd52a2d91102b525b0aafc1e14a2386
foreach ($cores in 1, 2) {
    & $cmake -S firmware -B "firmware/build/dht22-pio-rtos-$cores" @base -DMOSAIC_BUILD_RTOS=ON "-DMOSAIC_RTOS_CORES=$cores" "-DFREERTOS_KERNEL_PATH=$kernel" -DMOSAIC_HEALTH_STALL_TASK=0
    & $cmake --build "firmware/build/dht22-pio-rtos-$cores" --target mosaic_node_rtos -j 4
}
git diff --check
```

The collector is `EXCLUDE_FROM_ALL`; explicitly build its target. To change
sample count, reconfigure with `-DMOSAIC_DHT22_VALIDATION_ATTEMPTS=200`, then
rebuild. This setting changes only the collector. It does not relax spacing.
Host tests execute pure C decoding/record logic, not PIO instructions, GPIO,
DMA, sensor timing or FreeRTOS. Missing-edge host cases are full arrays with
zero-filled suffixes, never out-of-bounds short buffers.

`CMAKE_OBJECT_PATH_MAX=200` avoids a Windows dependency-file path limit reached
by the collector's SDK assembly object with this repository's long absolute
path. The initial collector build failed on that path, then passed after this
configure setting. It changes build object paths only. UTF-8 mode makes Python's
implicit text reads match the UTF-8 frozen-oracle sources on Windows; it changes
the test interpreter mode, not PC source files.

### Local execution evidence

Compiler/tooling: installed Pico SDK **1.5.1**, Arm GNU **10.3-2021.10**,
FreeRTOS-Kernel **V11.2.0** at the pinned revision above, host GCC **14.2.0**,
Python **3.12.7**. All builds used `PICO_BOARD=pico_w` and separate ignored
directories under `firmware/build/`. No Wi-Fi credentials/PC IP were supplied;
the existing configure warning correctly says these binaries will not send
telemetry. The RTOS builds use `MOSAIC_HEALTH_STALL_TASK=0` and no audio task hook.

| Check | Result | Local evidence |
| --- | --- | --- |
| Environmental C host tests, `-Wall -Wextra -Werror` | PASS | `firmware/build/dht22-validation-host/environment_host_test.exe` |
| Full PC suite, default Windows text mode | 241 run, 1 frozen-oracle hash failure | `firmware/build/dht22-pc-tests.log` |
| Full PC suite, explicit UTF-8 mode | PASS: 241 tests, 209.757 s | `firmware/build/dht22-pc-tests-utf8.log` |
| Standard Pico W default build, all existing targets | PASS | `firmware/build/dht22-standard-build.log` |
| RTOS one-core `mosaic_node_rtos` | PASS | `firmware/build/dht22-rtos-1-build.log` |
| RTOS two-core `mosaic_node_rtos` | PASS | `firmware/build/dht22-rtos-2-build.log` |
| Explicit `dht22_pio_validation` target | PASS after object-path setting | `firmware/build/dht22-dedicated-build.log` |
| Default-build exclusion | PASS: collector UF2 absent after default build, present after explicit target | Observed during this run |
| Integer-only source / unchanged production interfaces | PASS: 8 source files scanned; protected production trees identical to `HEAD` | Source scan and `git diff HEAD` |
| Whitespace check | PASS, including separate new-file whitespace scan | `git diff --check` |
| Pico W execution / logic analyzer / fault recovery | NOT RUN | Hardware worksheet remains unfilled |

The first PC run's sole failure was
`tests.test_integer_accuracy.IntegerAccuracy.test_float_oracle_is_frozen`.
The test and both oracle files match `HEAD`; reading the UTF-8 oracle explicitly
reproduces the expected hashes. The default Windows `cp1252` text read produces
a different string/hash. No unrelated oracle/test files were edited to make the
suite pass. Software evidence cannot establish any hardware acceptance result.

## Real Pico W procedure and acceptance criteria

1. Check GP2 DATA, 3.3 V pull-up and common ground. Keep PIR GP16, CO2 UART1
   GP8/GP9 and microphone GP26/ADC0 wiring unchanged. Use short DATA wiring.
   Connect a logic analyzer ground and GP2 channel at >=10 MS/s. Document module,
   supply, pull-up, cable length, firmware revision and analyzer sample rate.
2. Build the optional target above. **Manually** flash
   `firmware/build/dht22-pio-validation/tests/dht22_pio_validation.uf2`
   via BOOTSEL. This work does not flash hardware. Open USB CDC serial at
   115200 (USB CDC does not use a physical 115200 baud wire); save the full log.
   If startup lines were missed, reset RUN with logging ready, or capture on
   serial reconnect. The firmware waits 2.5 s, runs 100 attempts and then idles.
3. Collect the healthy run through `SUMMARY` / `END`, about 4 min 10 s after
   reset. Aim for 100/100 valid readings with no errors on a stable bench; record
   every failure rather than concealing it with retries. A lower rate needs
   wiring/load investigation, not a claim that building proved reliability.
   Check status totals equal attempts and duration count equals starts.
4. Trigger GP2 falling and capture the entire exchange. Confirm start LOW near
   **1105 us**, released HIGH before the sensor reply, two response phases and
   all forty bits. Suggested bench check: start LOW within 1% of 1105 us after
   verifying the system clock; at least 2.5 s between host starts. Nominal total
   wire acquisition is about 4.3..6.2 ms depending on data bits. The manual's
   timing extremes give roughly 4.075..6.675 ms for this start, before software
   overhead; these are calculations, not measurements. Healthy observed latency
   should normally stay below 8 ms in this standalone target. Treat exceeding
   that target as a scheduling/timing investigation; the driver cutoff is 10 ms
   only for incomplete captures, observed when service runs.
5. Compare per-attempt response, bit LOW and bit HIGH ranges with the GP2 trace.
   Counts should be a few us shorter, still within the accepted decoder windows.
   Valid zero HIGHs are 15..40, one HIGHs 50..90; no valid HIGH is 41..49. Confirm
   byte order/checksum against an analyzer decode or manual forty-bit decode.
   Two clusters and plausible readings alone do not demonstrate calibration.
   A digital trace shows timing, not conclusively that HIGH is undriven; source
   inspection plus an analog rise-time trace can establish release behavior.
6. In a separate reset/run, collect healthy frames, disconnect sensor DATA
   leaving the pull-up, then reconnect before attempt 100. Repeat with DATA held
   LOW through suitable current-limiting test wiring. For stuck HIGH, use the
   disconnected sensor/pull-up condition; do not tie DATA directly to 3.3 V
   against the Pico's start LOW. Expect TIMEOUT, invalid DHT bits, retained last
   numbers/sample time, and no pulse statistics from partial/old buffers. A
   nominal timeout is >=10,000 us plus polling/cleanup; a useful standalone
   target is <11,000 us without exceptional interrupt delays. Record outliers.
   After release/reconnect, expect a valid later attempt without reboot; allow
   2 s sensor warm-up if its power was removed. Never present retained numbers
   from a failed attempt as a fresh valid measurement.
7. If an existing open-drain waveform fixture is available, disconnect the real
   sensor and inject a valid frame, negative temperature, bad checksum,
   out-of-range frame, HIGH 41..49, and missing final falling edge. Expect
   OK/negative value, CHECKSUM ERROR, OUT OF RANGE, PROTOCOL ERROR (or TIMEOUT
   if capture cannot finish), and TIMEOUT respectively. Restore a valid frame
   to prove recovery. A floating/unplugged line does not test checksum errors.
   The collector requires no fixture or new hardware dependency to run normally.
8. Separately run `mosaic_sensor_test` and the usual configured `mosaic_node` /
   `mosaic_node_rtos` builds for >=10 minutes with all sensors connected. Confirm
   CO2 warm-up then replies, PIR changes, telemetry/CONFIG/watchdog progress and
   no reset when DHT is unplugged/reconnected. Test one and two cores; for actual
   audio coexistence supply the team's existing audio task hook and capture
   audio progress/drop evidence alongside GP2. The default SMP build has no
   audio task. Observe existing audio IRQ ownership, DMA channel separation and
   any RX FIFO stall with a debugger/trace if investigating failures. Do not
   equate the combined foreground ADC test with continuous audio DMA testing.

## Hardware evidence worksheet (not yet measured)

Copy summary values and retain raw logs/traces. Separate healthy, fault and
concurrent-load runs; use `NA` for a timing group without samples. Do not replace
missing measurements with the calculated expectations above.

| Run / configuration | Attempts / starts / valid | Timeout / checksum / protocol / other | Observed valid min / avg / max us | Observed timeout min / avg / max us | GP2 trace / USB log |
| --- | --- | --- | --- | --- | --- |
| Healthy GP2, standalone | Not measured | Not measured | Not measured | Not measured | Pending |
| DATA unplugged, then restored | Not measured | Not measured | Not measured | Not measured | Pending |
| DATA LOW, then restored | Not measured | Not measured | Not measured | Not measured | Pending |
| Optional waveform faults/recovery | Not measured | Not measured | Not measured | Not measured | Pending |
| Normal node, Wi-Fi + sensors | Not measured | Not measured | Not instrumented by collector | Not instrumented by collector | Pending |
| RTOS one core / two cores + actual audio | Not measured | Not measured | Not instrumented by collector | Not instrumented by collector | Pending |

Also record response LOW/HIGH ranges, data LOW/HIGH ranges and valid zero/one
HIGH ranges from each collector summary; physical start LOW and start spacing
come from the analyzer. Production load rows need external traces and existing
node/audio status evidence; this standalone target is not linked into the node.
No CPU load, cycle saving, physical sensor accuracy, long-term success rate,
bus starvation tolerance, electrical rise time or watchdog behavior was measured
by software-only validation.

## File-by-file change summary and professor explanation

- `firmware/tests/dht22_pio_validation.c`: optional GP2 hardware collector using
  the production asynchronous driver; integer status/duration/pulse statistics,
  fixed storage, delayed USB output and timeout buffer exclusion.
- `firmware/tests/CMakeLists.txt`: explicitly requested USB-only collector
  target and bounded configurable attempt count; normal targets remain intact.
- `firmware/tests/environment_host_test.c`: preserves all existing tests and
  adds endpoint combinations, every bit position, invalid timing at every bit,
  all ambiguous HIGHs, missing-suffix representations, negative/checksum/range
  pipelines, failure retention/recovery and future/stale timestamp regressions.
- `docs/dht22_pio_validation.md`: source audit, calculations, reproducible checks,
  hardware instructions, acceptance targets and unfilled evidence worksheet.

Production `.pio`, driver headers/C, environmental processing, audio interfaces,
PIR/CO2, networking/packet formats/dashboard and watchdog are unchanged. The
untracked root `mic_test.c` is untouched. No commit, push, merge or flash occurs.

Explain the design to the professor as follows: “Our PIO assembly implements the
open-drain start and edge counters with a deterministic two-clock inner loop.
DMA transfers 82 pulse counts while ARM can service other work. ARM then checks
timing, reconstructs forty bits and validates the checksum/range. We measured
success and observed latency on hardware using a separate collector, with a
logic analyzer for exact physical timing.” Use the final sentence about measured
results **only after filling the worksheet with real logs and traces**. Until
then say that the collector and host checks are ready, and hardware results are
pending. Meaningful low-level work is the verified timing/resource design and
its failure behavior, not the number of assembly instructions.
