# Subsystem 3 environmental migration

## Scope and status

Continuation on `feat/utk-subsystem3-environment`, based on
`986510ff767734cb6edcf42504b29f001fa270b6`. All results are provisional against
an uncommitted working tree, as requested. Old logs/results are retained.
No other subsystem, original checkout, kernel, device, library, shared
makefile, or host installation was changed. No commit/push/branch change.

Before this continuation: fixed-point decoding, status/expiry helpers,
ACD protocol state, S5 flag mapping, PIR in the consumer, and three host
executables existed. This continuation moves PIR intact into a dedicated
sensor task and implements the two missing acquisition paths.

- IMPLEMENTED AND TESTED (host): scheduling/config validation, S5 calls with
  test doubles, UART transport and actual register-driver logic with MMIO
  doubles, DHT capture state/timeout/recovery with hardware doubles, original
  decode/expiry tests, and PIO assembly reproducibility.
- IMPLEMENTED, HARDWARE UNVERIFIED: environment task, UART1 acquisition,
  PIR acquisition, and DHT PIO/DMA hardware path for `WIFI=cyw43` with SDK 2.2/2.3.
  The latter has been source-reviewed against SDK 2.2, but has NOT been
  compiled/linked against that SDK here. The hardware doubles do not establish
  actual SDK linkage, PIO timing, DMA operation or sensor behavior.
- BLOCKED: full USB/Wi-Fi/MQTT firmware verification (only SDK 1.5.1 is installed).
  No WSL distribution or repository Docker/devcontainer setup was found.
- NOT IMPLEMENTED: DHT acquisition in `WIFI=none`. That profile does not link
  PIO/DMA or the shared SDK allocator; init explicitly returns unavailable,
  and telemetry reports DHT invalid/resource error. No fallback/fake samples.
- BLOCKED: physical testing; no board test was performed. A successful build
  does not mean the task has been observed running.

## Task, ownership and resource budget

`subsystem3_start`, called serially by the initial task, explicitly creates and
starts both S3 tasks with `tk_cre_tsk` and `tk_sta_tsk`. The environment task
uses priority 17/core 0 (SMP affinity conditional). It uses `tk_get_otm` (monotonic operating milliseconds)
and `tk_dly_tsk(10)`. All other subsystem objects exist before start. The
priority-16 example consumer retains its original S2/S4 behavior. A failed
create/start returns an error; already-started tasks remain owned and a failed
start retains its dormant object for retry. Repeated calls do not create a
second consumer, and successful startup is idempotent. The shared
`app_start_task` is not used here because it returns an ID after a failed
`tk_sta_tsk`. A started task found dormant is treated as unexpectedly exited:
S3 refuses an unsafe restart and requires a node reset. On a handled environment
task error, active DHT capture is stopped, its public task ID is atomically
cleared, and static hardware resources are retained. No task is deleted while
it might use shared resources. The atomic progress counter and kernel task
state provide liveness evidence beyond a task ID.
No sensor ISR, task-per-sensor, networking call or floating-point arithmetic
is introduced. Only the allowed read-only `cyw43_utk_get_status` call is used.

One task owns GP2 (DHT), UART1 GP8/GP9 and GP16 (PIR). The template only boots
the UART0 kernel device; S3 does not initialize `serb` or touch UART0. UART1
reset uses atomic aliases for that peripheral only. The UART divisor uses
`CLK_PERI_FREQ` from the board's 125 MHz clock configuration, Q6 rounded to
nearest (IBRD 6510, FBRD 27), FIFO enabled, 1200 8N1, IRQs/DMA disabled.
GPIO input errors and FIFO contamination invalidate only CO2.

The application uses six tasks now, plus initial/USB/Wi-Fi tasks (nine versus
32 configured task slots with both services). S3 adds one 2048-byte task
stack and approximately 504 bytes static state in the measured Arm build;
its 328-byte DMA buffer has task-lifetime storage. No new kernel mutex,
mailbox or other object is required. Target stack/heap high-water marks have
NOT been measured. Linker SRAM region is 256 KiB; UART SMP test build BSS is
16,688 bytes, but Wi-Fi and runtime allocations must be measured separately.

## DHT allocation and PIO build

The existing 20-instruction DHT PIO program is unchanged. It drives LOW and
releases the pin; 82 pulse counts are captured via RX DREQ into DMA at 2 MHz,
with integer pulse decoding/checksum/range checks. Completion records service
time separately from capture-start sample time. Timeout cleanup disables PIO,
releases DATA, requests DMA abort, and polls the channel CTRL.BUSY bit on later
calls. RP2040-E13 permits ABORT to clear before an in-flight write retires;
BUSY, not ABORT, is the documented retirement condition. The SDK 2.2
`dma_channel_abort()` implements that condition with an unbounded spin. S3
uses the same request and BUSY check asynchronously to preserve service of
other sensors. Both IRQ routes stay disabled, and the channel's IRQ status is
cleared after BUSY goes low, with a compiler barrier before buffer use. A
timed-out capture remains a timeout even if a late completion occurs. If BUSY
never clears, the task leaves the static buffer, PIO and DMA channel allocated
and never decodes, reuses, or unclaims them; other sensor service continues. A
reset is needed to recover from a permanently stuck DMA. This assumes the
RP2040's documented BUSY behavior; hardware validation remains necessary.
References: [RP2040 datasheet, E13](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf)
and [Pico SDK 2.2 DMA API](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2_common/hardware_dma/include/hardware/dma.h).
It never spins for sensor edges or DMA completion, never reuses an in-flight
buffer, and clears only its channel's IRQs/error bits. Both DMA IRQ routes
are disabled. Claims are retained for task lifetime; initial resource failure
requires reboot after resolving contention.

The earlier race analysis used SDK 1.5.1. In supported SDK 2.2,
`pio_claim_free_sm_and_add_program` locks instruction-space search/insertion
and returns failure safely; S3 uses it, then non-required DMA allocation.
DMA exhaustion rolls back the SM/program. No PIO block, SM, program offset
or DMA channel is hardcoded, and no separate allocator bitmap is introduced.
S3 waits for the radio's `init_complete` (even if association failed), allowing
its allocation first. If initialization never completes, DHT stays explicitly
invalid; CO2/PIR/S5 continue. Audio must use the same allocator and declare its
own resources. Concurrent later Wi-Fi/audio allocations and total program
capacity still require a combined bench test.

Reference checked: [SDK 2.2 PIO allocator source](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2_common/hardware_pio/pio.c).
The template already links PIO/DMA/GPIO in the Wi-Fi profile and supplies its
SMP-safe claim-lock implementation. Therefore **no shared build or Wi-Fi
patch is required for the supported Wi-Fi profile**, and none is proposed or
applied. The template's local `pico/version.h` says 2.1.0 regardless of actual
SDK; do not use that header as an installation-version check.

`dht22.pio.h` is checked in, like the template radio PIO header. Reproduce with:

```text
pioasm -o c-sdk node/app_program/subsystem3/dht22.pio node/app_program/subsystem3/dht22.pio.h
python node/testing/subsystem3/host/check_pio.py <path-to-pioasm>
```

The check compares instructions and wrap bounds, allowing formatting/metadata
changes between assembler versions. Installed pioasm 1.5.1 reproduces the
RP2040 instructions. Regenerate/check after every PIO source edit.

## Scheduling, failures and S5 semantics

DHT starts after at least 2 s task warm-up, then uses the current validated
config interval (2000..60000 ms) measured from the previous attempt. It starts
only after potentially blocking S5 calls and a fresh monotonic timestamp.
CO2 warms for 120 s, then uses its configured 1000..60000 ms request cadence,
with a 1000 ms response deadline. Its read-only command remains FE A6 00 01 A7.
At most nine response bytes or 32 stale bytes are drained per service call;
no waiting for bytes. UART errors, checksum errors, missing responses and
failed TX invalidate CO2 without stopping DHT/PIR. Warm-up completion is
latched, preventing it from recurring after half a timer wrap.

PIR is sampled once per elapsed 100 ms; missed samples are skipped, never
invented. Config is checked every 250 ms, including all protocol fields and
version ordering; S5's version-zero boot default is accepted. On getter error
or invalid config the last good/default snapshot remains. ENV/PIR posts occur
at most once per 100 ms. During an active DHT capture S5 calls are deferred;
abort retirement does not block other sensor reporting. S5 takes at most
10 ms per mutex attempt, so a loop can incur 30 ms of S5 wait plus kernel
scheduling latency. Errors/counters and last return values remain in the
private `service` object for debugging.

PIR counts retry on E_TMOUT/E_OBJ (known pre-copy failures). Other errors may
be unlock failures after copying, so that batch is discarded to avoid double
counting. A batch older than 2 s is discarded and a drop event counted.
Environmental posting replaces a snapshot, so retrying cannot duplicate
counts. No hardware lock or S3 shared-data mutex is held across S5 calls.

Numeric contract remains signed tenths C, unsigned tenths %RH, integer ppm,
8-bit validity and 32-bit millisecond timestamps. Unsigned elapsed checks
reject future timestamps in the upper half range. All service gaps/deadlines
must remain below 2^31 ms. Expired validity is cleared and never resurrected
by subsequent wraps. Values retain last successful readings but flags/status
must always be checked. The formatter now handles tiny and zero-size buffers
without pulling newlib syscall/heap dependencies into the kernel image.

## Freshness mismatch and narrow S5 recommendation

S3 expires DHT at age >6000 ms, CO2 >5000 ms and PIR >1000 ms. Config permits
DHT/CO2 intervals to 60000 ms. S5 expires the combined environment at >6000 ms
since **posting**, not since acquisition, and accepts no per-channel times.
These limits are preserved. A 60 s interval deliberately has long stale gaps;
S3 periodically posts the current validity, including invalidations, without
refreshing its own sample times. It does NOT pretend that a repost is a new
measurement or extend freshness to fit config.

On S3 failure, S5 may retain the last posted valid channel up to its separate
6 s liveness window. With repeated failed posts of invalidations the absolute
sample age can exceed S3's 5/6 s limit. This cannot be fully corrected using
the existing S5 signature. Recommendation for ZhiHao: add an age-aware posting
API carrying separate DHT and CO2 sample ages; cache acquisition times and
apply per-channel expiry, while retaining the current function for compatibility.
Agree the product freshness policy before widening limits for 60 s intervals.
S5 has not been edited, and the wire format remains unchanged.

## Reproduction and remaining validation

Host tests (no persistent execution-policy change):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File node/testing/subsystem3/host/run.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File node/testing/subsystem3/build_uart.ps1
```

The build script uses existing Arm GCC 10.3.1 and MSYS make in a child-process
PATH, restores it, and writes separate immutable logs for SMP=0/1, TEST=0/1,
CONSOLE=uart WIFI=none. These are real kernel ELF/UF2 builds with the other
subsystems present, but exclude the SDK-dependent DHT hardware branch.

With a team-provided SDK 2.2/2.3 and appropriate compiler, run from
`node/build_make` on a supported build host:

```text
make -j4
make TEST=1 -j4
make NET=lwip MQTT=1 -j4
make NET=lwip MQTT=1 TEST=1 -j4
```

Use the existing private credential setup; never commit secrets. No dependency
was downloaded/installed here. Supported Wi-Fi/USB builds remain BLOCKED.

The 17 Nov correctness run adds host tests for task start/retry/exit, execution
progress through a sensor error, and DMA retirement with SDK register doubles.
The actual DHT hardware-boundary source is exercised with ABORT cleared while
BUSY remains set; a separate service test keeps BUSY set across many iterations
and checks that PIR, CO2 and S5 continue without buffer reuse. These tests
simulate hardware and kernel APIs. S3-U11 is still a target test and has not
been run on a board. See `TEST_LOG.md` for result and log links.

The S3-to-S5 freshness limitation and the shared S4/S5 MQTT bridge remain team
integration dependencies. Changes to shared kernel/network code require the
team and instructor agreement already specified in `TEAM.md`; no such change
is included in this work.

Hardware checklist (save fresh test IDs, commit and console/analyzer evidence):

1. Check GP2 pull-up to 3.3 V, shared ground, UART voltage levels and crossed
   TX/RX GP8/GP9; PIR output must be Pico-safe. Allow PIR stabilization.
2. Run target S3-U11, S3-U01 and INT-01; confirm the new task and original
   S2/S4 traffic remain live. Measure task stack/heap use under Wi-Fi load.
3. Analyze DHT start LOW (~1.1 ms), release and 82 pulse widths, minimum 2 s
   spacing, valid negative temperature and humidity. Disconnect/short DATA
   appropriately for bench testing; verify timeout, invalid flags, continued
   CO2/PIR and reconnect recovery. Check DMA IRQ isolation and resource
   exhaustion, including Wi-Fi/audio coexistence and radio reconnects.
4. Analyze UART1 1200 8N1: no request before 120 s, exact read command, valid
   nine-byte responses, checksum/header/UART-error rejection, 1 s timeout,
   disconnected/reconnected sensor and busy/noisy FIFO recovery.
5. Apply configs at interval bounds and mid-capture, verify actual cadence;
   select 60 s intervals and observe the documented stale gaps. Exercise S5
   contention and invalidation delivery; compare MQTT bytes with protocol v2.
6. Move/stay still after PIR stabilization; verify sample ratios and no
   double counting after a posting timeout. A pulled-down disconnected input
   reads low and cannot prove an empty room or healthy sensor.

The 10 ms kernel tick means a 10 ms requested delay is quantized; higher-priority
work can delay service further. The DHT timeout is observed at the next service,
not a strict 10 ms real-time guarantee. At 1200 baud a 32-byte UART FIFO spans
about 267 ms; long scheduling stalls can overflow it and must be measured.
No deadline, hardware throughput, radio coexistence or hardware accuracy claim
is made from host tests/cross-builds.

## File map

- `subsystem3.c/.h`: create/start environmental task, preserve example objects.
- `task_consumer.c`: PIR work relocated; final example behavior matches HEAD.
- `task_environment.c`: monotonic kernel task, radio allocation gate, bounded delay.
- `environment_service.c/.h`: config/sensor scheduling, S5 posts/error handling.
- `drv_uart1.c/.h`: actual UART1 MMIO transport without SDK UART/runtime.
- `drv_acd1100.c/.h`: bounded transport service around existing parser.
- `acd1100_protocol.c/.h`: existing parser plus latched warm-up.
- `drv_dht22.c/.h`: capture lifecycle/decoding; `drv_dht22_hw.c`: real SDK PIO/DMA.
- `dht22.pio/.pio.h`: original PIO source and reproducible generated program.
- `drv_pir.h`: owning-task comment; `drv_pir.c` remains the previous GPIO driver.
- `environment.c/.h`: previous fixed-point/expiry code, formatter edge-case fix.
- `s3_time.h`: shared wrap-safe elapsed checks; `s3_telemetry.c/.h`: previous mapping.
- `subsystem3_test.c`: additional target task-start check.
- `TEAM.md`: pins, UART1/dynamic PIO/DMA claims and S3 task budget.
- `testing/subsystem3/host/`: original tests retained, service/transport/recovery,
  MMIO and PIO reproduction tests added; test boundaries only live here.
- `testing/subsystem3/build_uart.ps1`, this document, `TEST_LOG.md`, `logs/`:
  reproducible builds, limitations, append-only results and evidence.

## Current test-only diagnostics

See `HARDWARE_EVIDENCE.md` for the TEST=1 snapshot fields, physical procedures, test IDs and the B4/N3 checklist. The on-target observations have not been run. The separate environmental numeric contract is in `docs/environment_numeric_representation.md`. A test-only observer task reads snapshots for approximately 327 seconds while the S4/S5 startup self-tests proceed; it does not acquire sensor data, and deletes itself on completion.
