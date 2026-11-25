# Arif integration handoff — 11 November 2026

> **Historical record (status at hand-in, 25 Nov 2026).** A handoff note from 11 Nov, written for the earlier CMake/FreeRTOS firmware that sent UDP. The submitted node runs µT-Kernel 3.0 and sends MQTT (`node/`). For the system as submitted, start at the [main README](../README.md) and the [evidence index](README.md).

## What is ready

- Protocol-v2 UDP telemetry, CONFIG/PING filtering, background Wi-Fi servicing.
- Bounded telemetry retries and duplicate-aware PC tracking (not a certified
  packet-loss fix; see `packet_loss_retry_status.md`).
- Opt-in RTOS node with network/environment/health tasks and watchdog gating.
- Bounded audio result handoff, configuration snapshot API and optional team
  audio task/core-1 hook. No producer is linked in the normal image.
- Read-only dashboard snapshot checker, with optional CONFIG/sensor/audio checks.

Supplied 9 November hardware logs showed steady RTOS task progress, stable heap,
CONFIG acknowledgement and an environment-task fault followed by a watchdog
reset. Normal firmware was restored and progress resumed. These are observed
functional checks, not a measured real-time or loss-free soak result. Router
outage recovery could not be run. Previous unexplained restarts remain open.

## Bring and set up

Bring the Pico W, USB data cable, laptop, repository and the pinned kernel
checkout. Tomorrow's sensor/microphone wiring must be checked with their owners.
Pins: DHT22 GP2, PIR GP16, CO2 UART1 TX GP8/RX GP9, mic ADC0 GP26. Use the team's
agreed voltage-divider/signal-conditioning circuit; do not infer wiring from
software alone. No sensor accuracy has been established with the bare Pico.

1. Join the same network as the nodes. Campus client isolation and the iPhone
   hotspot have not been validated; check connectivity on the actual venue
   network before relying on either.
2. Update the private `firmware/node/node_config.cmake`: SSID/password and the
   laptop's current LAN IP. On macOS, `ipconfig getifaddr en0` works if Wi-Fi is
   en0. Check the active Wi-Fi interface if it returns no address. Never commit
   the private file or a credential-bearing UF2/generated config header.
3. Each physical Pico needs a unique ID (1–8). Explicit `-DMOSAIC_NODE_ID=N`
   now overrides private-file defaults. Use separate build directories per node.

Normal one-core RTOS build, using this machine's prepared kernel dependency:

```sh
cmake -S firmware -B firmware/build-node -DMOSAIC_BUILD_RTOS=ON \
  -DFREERTOS_KERNEL_PATH="$PWD/firmware/build-node/_deps/freertos-kernel" \
  -DMOSAIC_RTOS_CORES=1 -DMOSAIC_NODE_AUDIO_SOURCES= -DMOSAIC_HEALTH_STALL_TASK=0
cmake --build firmware/build-node --target mosaic_node_rtos -j4
```

The kernel is V11.2.0, pinned to commit
`0adc196d4bd52a2d91102b525b0aafc1e14a2386`. Another machine needs its own
checkout and SDK/toolchain paths. Do not delete this dependency while relying
on it. Build output/private settings are ignored by git.

Close serial with Ctrl+A, K, Y; enter BOOTSEL and copy:

```sh
cp -X firmware/build-node/node/mosaic_node_rtos.uf2 /Volumes/RPI-RP2/
```

The volume disappears on reboot. Reopen the current port from
`ls /dev/cu.usbmodem*`, using `screen PORT 115200`.

## PC session and evidence

Use one dashboard process; it already includes the UDP gateway. From `pc/`:

```sh
python3 -u -m mosaic.dashboard --verbose --csv integration.csv \
  --events integration.jsonl 2>&1 | tee integration-console.log
```

Use fresh filenames for separate test sessions; CSV/events append. Open
`http://localhost:8050`. In another terminal (any folder for curl):

```sh
curl -H 'Content-Type: application/json' -d '{"report_interval_ms":1000}' \
  http://localhost:8050/api/nodes/1/config
```

Check CONFIG_ACK OK, then from `pc/`:

```sh
python3 -m mosaic.integration_check --nodes 1 --require-config
```

For the second real Pico: `--nodes 1 2`. Add `--require-sensors` only after
connecting sensors and allowing CO2 warmup. Add `--require-audio` only after
the real producer is linked. `--save FILE.json` preserves an exclusive new
timestamped snapshot. This check is not a soak or classifier-accuracy test.
Telemetry loss/reboots are cumulative across the running gateway session.

## Audio handoff — resolve labels before enabling

The present classifier has **background / generic speech / transient** outputs.
Protocol v2 expects **background / lecturer speech / student conversation /
transient**. Generic speech cannot establish speaker identity. Moe, Darius,
ZhiHao and Arif must agree a compatible model or an explicit protocol/fusion
change; do not put generic speech into either identity class silently.

The producer implements `void mosaic_node_audio_task(void *)` and never returns.
Add its source(s) through `MOSAIC_NODE_AUDIO_SOURCES` and configure
`MOSAIC_RTOS_CORES=2`. The node creates it on core 1; network/environment/health
stay on core 0. Audio/DSP initialization and DMA IRQ enabling must happen in
that task, so the IRQ is enabled on the audio core. Do not launch core 1 manually
when using the SMP kernel.

- Include `firmware/node/node_audio.h` (exported include directory).
- Read `mosaic_node_audio_config()` once per window; honour gain/threshold or
  clearly report unsupported settings. Current baseline stores gain but does
  not implement an audio sample multiplier.
- Publish one owned `mosaic_audio_window_t` per completed 500 ms window through
  `mosaic_node_audio_publish(&result, dsp_us, inference_us)`. Use the agreed four
  classes, 0–100 probabilities, zero reserved byte, RMS x16. Ownership stays with
  the producer; the handoff copies the record. Report UNKNOWN below threshold.
- Call `mosaic_node_audio_dropped(n)` for actual lost capture windows; it preserves
  sequence gaps and prevents falsely consecutive two-window batches.
- Call `mosaic_node_audio_progress()` after each bounded processing iteration,
  including invalid-signal handling. Never call it from a DMA ISR to hide a
  hung task. When an audio producer is linked, its progress is required to feed
  the watchdog. Initialization/blocking work must remain below the watchdog budget.
- The handoff retains the newest two results, counts overflow and reports maximum
  timing. Longer report intervals can discard older windows; they cannot promise
  every 500 ms result. A 1 s report may contain fewer than two at startup or due
  to scheduling/processing delay; inspect sequence gaps and timing over a run.
- ADC capture is single-consumer. Do not share its DMA buffers after the next
  acquisition call; feature/DSP code is not reentrant. Respect DHT PIO/DMA ownership.

Example configure additions after the team supplies a task file:
`-DMOSAIC_RTOS_CORES=2 -DMOSAIC_NODE_AUDIO_SOURCES=/absolute/path/team_audio_task.c`.
For multiple sources pass a quoted semicolon-separated CMake list. The default
extra libraries are `audio_capture;audio_dsp`; add classifier/timing source files
or suitable libraries explicitly. These hooks are build-tested, not a completed
audio implementation or hardware-validated SMP claim.

## Run order tomorrow

1. One real node ONLINE; serial task progress; CONFIG ACK and applied version.
2. Actual sensor values/validity with Kendrick; CO2 warmup is not a valid CO2 value.
3. Label agreement, then real audio task: two-window transport, sequence/drop
   counts, DSP+inference timing with Wi-Fi. Accuracy and microphone signal quality
   stay with their owners; transport alone does not validate either.
4. Two unique node IDs ONLINE; CONFIG to node 2 leaves node 1 unchanged.
5. Reconnect test on a controllable network; watchdog must not reset a healthy
   network task that is iterating while disconnected.
6. Isolated 10-minute soak with start/end evidence. N10 remains open until its
   loss, restart and (when integrated) audio-overrun criteria are measured.

If audio is not ready, demonstrate real sensors/CONFIG/health first. A separate
`--scenario lecture` dashboard can rehearse fusion, but it is simulated evidence,
never substitute it for a successful real-audio test. Do not run two gateways on
the same UDP port. Existing software results and observed hardware checks should
be kept distinct from tomorrow's pending checks.
