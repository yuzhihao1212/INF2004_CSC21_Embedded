# Audio port test cases and results

Test cases are defined before execution. Original example tests/results stay intact.

| ID | Method | Expected result |
|---|---|---|
| S1-U04 | `py node/testing/subsystem1/test_audio_port.py` compiles actual C reference and migrated implementations | Exact equality of 20 Q8 features across 32 deterministic raw ADC windows |
| S1-U05 | Cross-build SMP=1, USB console, Wi-Fi profile; inspect port objects with `nm` | UF2 links; no floating-point runtime references from audio/ML objects |
| S1-U06 | Hardware GP26 microphone, 60 s capture with Wi-Fi traffic | 16 kHz acquisition, roughly 120 windows, no hangs; record actual gaps, drops and maximum DSP duration |
| S1-U07 | Hardware stalled classifier / saturated feature queue | Capture does not block on queue; dropped windows counted; state recovers |

## Results

Additional case S1-U08 (17 Nov): build standalone audio_benchmark/audio_talking
and the micro T-Kernel image, audit project audio/ML objects for float/double
helpers and libm calls, and replay both current DSP implementations against
the pinned historical Git blob. Expected: no project audio floating-point
operations and all 20 features unchanged. Historical host-only baseline is
intentionally allowed floating-point startup; it is never a firmware source.

| Date | ID | Commit | Result | Evidence |
|---|---|---|---|---|
| 2026-11-16 | S1-U04 / S2-U03..05 replay run | `55476b0` | FAIL (harness) | `logs/2026-11-16_audio-replay.txt`; an independent clipping case reused the preceding timestamp/state, correctly triggering TIMING_FAULT first; reset the fixture before that case |
| 2026-11-16 | S1-U05 USB/Wi-Fi cross-build | `55476b0` | PASS (link only) | `logs/2026-11-16_usb-wifi-build.txt`; dual-core UF2 generated, hardware NOT RUN |
| 2026-11-16 | S1-U04 replay | `b2385d8` | PASS | `logs/2026-11-16_audio-replay-r2.txt`; all 20 features identical across 32 windows |
| 2026-11-16 | S1-U05 integer symbol audit | `b2385d8` | PASS | `logs/2026-11-16_audio-symbols.txt`; no float helpers/libm calls in ported objects |
| 2026-11-16 | S1-U05 MQTT profile | `b2385d8` | BLOCKED (configuration) | `logs/2026-11-16_mqtt-build.txt`; missing private wifi_secrets.h, not an audio compilation failure |
| 2026-11-16 | S1-U05 MQTT profile with example-only configuration | `b2385d8` | PASS (link only) | `logs/2026-11-16_mqtt-example-build.txt`; ignored build directory supplied public example header using INCPATH; no template/config sources edited, no real connection tested |

S1-U06/U07 are NOT RUN until real-board evidence is saved.

## Integer-only follow-up (17 Nov 2026)

| Date | ID | Commit | Result | Evidence |
|---|---|---|---|---|
| 2026-11-17 | S1-U08 / S1-U04 | `a60322d` | PASS | `logs/2026-11-17_integer-fix-replay.txt`: both current standalone and kernel DSP match the historical baseline on 32 windows |
| 2026-11-17 | S1-U08 source audit | `a60322d` | PASS | `logs/2026-11-17_integer-fix-source.txt`: 41 project audio/ML C/header files, build folders excluded; no float types, literals or floating printf conversions |
| 2026-11-17 | S1-U08 object audit | `a60322d` | PASS | `logs/2026-11-17_integer-fix-symbols.txt`: no float/double helper or libm references in standalone and S1/S2 project objects |
| 2026-11-17 | S1-U08 standalone build | `a60322d` | PASS | `logs/2026-11-17_integer-fix-standalone.txt`: audio_benchmark and audio_talking UF2s link, float/double implementations disabled |
| 2026-11-17 | S1-U08 kernel build | `a60322d` | PASS | `logs/2026-11-17_integer-fix-kernel.txt`: dual-core USB/Wi-Fi UF2 links against SDK 2.2.0 |

Hardware remains NOT RUN. The historical float-initialisation implementation is
loaded by Git blob only into a temporary host test executable, never a Pico target.
