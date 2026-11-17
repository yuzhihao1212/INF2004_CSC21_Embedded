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
