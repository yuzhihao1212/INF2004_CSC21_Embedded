# FreeRTOS node bring-up

`mosaic_node_rtos` is an opt-in prototype. The existing `mosaic_node` remains
available. Both use the same private node settings and protocol v2. Neither
target integrates a classifier by default. Supplied 9 November logs confirm
one-core task progress, CONFIG ACK and watchdog reset after deliberate environment
task suspension. Exact reset latency, RTOS Wi-Fi outage recovery and soak criteria
remain unverified. Normal firmware was restored after the fault test.

Use FreeRTOS-Kernel V11.2.0, commit
`0adc196d4bd52a2d91102b525b0aafc1e14a2386`, from
[the official kernel repository](https://github.com/FreeRTOS/FreeRTOS-Kernel/tree/V11.2.0).
The Pico SDK/toolchain must already be configured as for the existing node.

```sh
cmake -S firmware -B firmware/build-node -DMOSAIC_BUILD_RTOS=ON \
  -DFREERTOS_KERNEL_PATH=/path/to/FreeRTOS-Kernel -DMOSAIC_HEALTH_STALL_TASK=0
cmake --build firmware/build-node --target mosaic_node_rtos -j4
```

Flash `firmware/build-node/node/mosaic_node_rtos.uf2`. The normal dashboard and
CONFIG commands remain the same. The RTOS target adds startup reset information
and periodic heap/stack high-water reports (stack values are 32-bit words).
`free_heap_bytes` reports the FreeRTOS heap; it is not the total unused RP2040 RAM.
CPU load remains unmeasured. No packet-loss performance improvement is claimed.

## Ownership and supervision

All three application tasks default to core 0. `MOSAIC_RTOS_CORES=2` enables SMP;
the existing application tasks are pinned to core 0. The environment task (priority 2, 2 ms period) owns
the sensor drivers. The network task (priority 2, 10 ms period) owns CONFIG,
telemetry, retries and foreground lwIP calls. Short critical sections protect
copies of sensor values/configuration and the IRQ control ring. No driver call
or network operation runs while holding the snapshot lock.

Wi-Fi still uses the SDK background IRQ architecture and its lwIP locks, with
the RP2040 FreeRTOS SDK synchronization/time adapters enabled. It does not use
the lwIP socket/sys_arch task architecture. The kernel timer task supports SDK
synchronization; it has priority 4. The supervisor has priority 3 and runs every
250 ms. The idle task remains available between scheduled application work.

Only the supervisor feeds the 8000 ms hardware watchdog, and only after both
application tasks have completed another loop since the previous feed. A Wi-Fi
disconnect or invalid sensor reading does not withhold a heartbeat if the task
continues iterating. A blocked task stops contributing. A supervisor/scheduler
hang also stops feeds. Allocation failure or stack overflow takes a bounded
reset path. USB startup and sensor setup occur before scheduler supervision.

The optional `MOSAIC_NODE_AUDIO_SOURCES` task hook starts the team's producer on
core 1 and includes its progress in watchdog gating. See
[the integration handoff](../../../docs/integration_arif.md) and `../node_audio.h`.
The three-class classifier and four-class wire labels must be reconciled first.

## Hardware checks still required

1. Confirm `RTOS: cores=1` for the normal build, telemetry and CONFIG ACK on the dashboard.
2. Disconnect Wi-Fi for longer than 8 seconds, then restore it: sensing/task
   progress should continue and reconnect should not cause a watchdog reset.
3. For a dedicated fault build, configure `MOSAIC_HEALTH_STALL_TASK=1` (network)
   or `2` (environment) and rebuild. That task suspends 30 seconds after boot;
   expect watchdog reset roughly 8 seconds after the last full heartbeat epoch,
   with up to one supervisor period of scheduling tolerance. Verify the next
   startup says `reset=watchdog`. This build deliberately repeats the fault.
4. Restore `MOSAIC_HEALTH_STALL_TASK=0`, rebuild and reflash after fault testing.

Host tests verify the shared feed gate (including a live peer masking a hung
task). They do not validate physical reset timing, RTOS scheduling or Wi-Fi
stability. Local builds use SDK 2.3.0; CI is configured to build both targets
against SDK 1.5.1, with results pending until the branch is submitted.
