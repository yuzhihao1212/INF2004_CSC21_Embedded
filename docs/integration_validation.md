# Integration preparation validation — 10 November 2026

- `python3 -m unittest` in `pc/`: **211 tests passed**. This includes the actual C
  watchdog gate in two-/three-task modes, audio handoff C-to-Python packet check,
  snapshot checker, protocol, gateway, CONFIG, fusion and evaluation tests.
- Local Pico SDK 2.3.0 / Arm GCC 15.2.1 builds: `mosaic_node`,
  `mosaic_node_rtos` and `audio_talking` succeed.
- A separate compile/link probe builds the optional SMP configuration with two
  cores, a supplied audio task entry, actual capture/DSP and int8 classifier references,
  audio heartbeat gating and explicit node ID 2 overriding the private default.
  The probe emits no audio; it is not hardware validation and must not be flashed.
- Final normal build is one core, node ID from the private file, no supplied
  audio producer, `MOSAIC_HEALTH_STALL_TASK=0`. Its UF2 remains at
  `firmware/build-node/node/mosaic_node_rtos.uf2`.
- `git diff --check` passes. Credentials, generated firmware and raw session
  logs are excluded from the source change.
- CI is configured to build both node targets against SDK 1.5.1 with the pinned
  FreeRTOS kernel; that CI run has not happened for these local changes.

Supplied hardware excerpts from 9 November establish RTOS loop progress,
CONFIG acknowledgement and watchdog reset under deliberate environment task
suspension, followed by normal firmware restoration. They do not establish
reset latency, uninterrupted long-run stability or performance under real audio.

Pending for integration: actual sensor/mic wiring and accuracy, the three-class
model/four-class protocol agreement, real audio/SMP scheduling and timing,
two-node targeting, controllable-network recovery and a passing isolated soak.
Raw RF loss and earlier unexplained resets are not declared fixed.
