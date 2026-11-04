# Week 10 Integration Test Plan

**Goal for Week 10:** one real Pico W node sends sensor data, and audio windows if ready, over
protocol v2 to the PC gateway. The PC reconfigures it and recovers from faults without anyone
touching the node. A second node and real-time classification are *should* items. Four-node
fusion follows after Week 10.

Each test has one pass criterion, one owner and saved evidence, so "is it done?" has a yes/no
answer. Mark results in the **Result** column (✅ / ❌ + note) and keep the evidence files in the
team drive under `week10/`.

| Priority | Meaning |
|----------|---------|
| **Must** | Needed to claim partial integration in Week 10 |
| **Should** | Planned for Week 10, but the demo survives without it |
| **Stretch** | Only if everything else passes |

## 0. Set-up (once)

| Item | Detail |
|------|--------|
| Network | A phone hotspot. Campus and guest Wi-Fi usually block device-to-device traffic. Keep the PC and every Pico on it. |
| PC IP | `ipconfig getifaddr en0` (macOS) or `ipconfig` (Windows). Note it: every node is built with it. |
| Node build | Copy `firmware/node/node_config.example.cmake` to `node_config.cmake`. Set `MOSAIC_NODE_ID` (unique per Pico), `MOSAIC_PC_IP`, `WIFI_SSID` and `WIFI_PASSWORD`. Then **CMake: Delete Cache and Reconfigure** and build `mosaic_node.uf2`. |
| PC | From `pc/`: `python3 -m mosaic.dashboard --verbose --csv week10.csv`, then open http://localhost:8050. Allow Python through the firewall on Windows. |
| Serial | Open the node's USB serial monitor for every test; it prints Wi-Fi status, IP and CONFIG results. |
| Labels | Write the node ID on each Pico with tape. |

## 1. Bench prerequisites (before integration day)

These decide whether audio can be part of Week 10 at all. Run them first.

| ID | Test | How | Pass criterion | Owner | Priority | Evidence | Result |
|----|------|-----|----------------|-------|----------|----------|--------|
| B1 | Mic hears speech | Darius's mic diagnostic: 30 s silence, then 30 s normal speech at 1–2 m | Speech RMS clearly above silence (≥ 3×) and no clipping | Darius | Must (for audio) | Diagnostic report + WAV | |
| B2 | DSP timing | Flash `audio_benchmark`; log ≥ 100 windows | DSP time p99 ≤ 300 ms per 500 ms window on one core (leaves ~100 ms for inference) | Moe | Must (for audio) | Serial log | |
| B3 | Inference timing | Darius's int8 model on the Pico, same windows | Inference p99 ≤ 100 ms; no floats in the per-window path | Darius | Should | Serial log | |
| B4 | Sensors | `mosaic_sensor_test` for 5 min next to a reference thermometer | DHT22 within ±1 °C / ±5 %RH; CO₂ valid after warm-up; PIR reacts to a hand wave | Kendrick | Must | Serial log + photo | |

## 2. One node, end to end

| ID | Test | How | Pass criterion | Owner | Priority | Evidence | Result |
|----|------|-----|----------------|-------|----------|----------|--------|
| N1 | Boot and Wi-Fi | Flash; watch serial | Prints `MOSAIC node N (protocol v2)` and `Node N IP …` within 30 s | Arif | Must | Serial log | |
| N2 | Telemetry arrives | Dashboard running | Node card **Online**; packet loss 0 %; seq counting up once per second | ZhiHao | Must | Screenshot + CSV | |
| N3 | Readings plausible | Compare with B4 reference | Temperature and humidity match the reference; CO₂ shows *Warming up* for ~2 min, then a value | Kendrick | Must | Screenshot | |
| N4 | Latency | Wait 1 min | Dashboard RTT shown; p95 ≤ 100 ms on the hotspot | ZhiHao | Must | Screenshot | |
| N5 | CONFIG applied | `curl -d '{"report_interval_ms": 500}' http://localhost:8050/api/nodes/N/config` | Console prints `CONFIG 1 applied`; node serial prints `CONFIG 1 applied`; reports now every 0.5 s | ZhiHao | Must | Console + serial log | |
| N6 | Bad CONFIG refused | Same curl with `{"report_interval_ms": 50}` | HTTP 400, nothing sent; node unchanged | ZhiHao | Should | Console | |
| N7 | CONFIG from another device ignored | From a second laptop on the hotspot, in `pc/`: `python3 -c "import socket; from mosaic import protocol as p; socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(p.encode(p.Header(p.MsgType.CONFIG, N, 0, 0), p.Config(99, report_interval_ms=200)), ('NODE_IP', 5006))"` | Node prints nothing; its `config_version` on the dashboard is unchanged | Arif | Should | Serial log | |
| N8 | Reboot recovery | Press the Pico's reset (or unplug for 5 s) after N5 | Gateway counts 1 reboot (not packet loss); CONFIG is re-sent automatically and applied again | ZhiHao | Must | Console | |
| N9 | Wi-Fi drop recovery | Turn the hotspot off for 30 s, then on | Node goes **Stale** (3 s) then **Offline** (10 s), then back **Online** by itself, no reset | Arif | Must | Console + serial | |
| N10 | Soak | Leave running 10 min | No reboots; loss < 1 %; no audio overruns (if audio is in) | Arif | Must | CSV + console summary | |

## 3. Audio in the node (depends on B1–B3)

| ID | Test | How | Pass criterion | Owner | Priority | Evidence | Result |
|----|------|-----|----------------|-------|----------|----------|--------|
| A1 | Windows arrive | Node with the audio task | Every report has `audio_window_count` = 2; no skipped windows (`audio_window_seq` +2 per report) | Moe + Arif | Should | CSV | |
| A2 | Real-time with Wi-Fi | 10 min with Wi-Fi active | DSP + inference p99 ≤ 400 ms; `audio_overruns` stays 0 | Moe | Should | CSV | |
| A3 | Speech vs silence | 1 min silence, 1 min talking, 1 min silence | Dashboard audio shows the change within ~2 s each time | Darius | Should | Screen recording | |

## 4. Two nodes and fusion

| ID | Test | How | Pass criterion | Owner | Priority | Evidence | Result |
|----|------|-----|----------------|-------|----------|----------|--------|
| M1 | Two nodes | Second Pico with a different `MOSAIC_NODE_ID` | Both cards **Online**; CONFIG to node 2 does not change node 1 | Arif | Should | Screenshot | |
| M2 | Mode switch | Click **Discussion** on the dashboard | Both nodes acknowledge the new mode; Classroom panel shows Discussion mode | ZhiHao | Should | Console | |
| M3 | Fusion on real data | Node 1 at the lecturer's desk, node 2 at a student desk; lecture for 2 min | Classroom shows **Focused lecture** (if A1–A3 pass) or at least **Occupied** from motion | ZhiHao | Stretch | Screen recording | |
| M4 | Reference calibration | After the reference-comparison PR is merged: calibrate with lecturer-only speech, then students talk near node 2 | Student zone goes **Talking**; lecture alone does not trigger it | ZhiHao + Darius | Stretch | Screen recording | |

## 5. Exit criteria for Week 10

- **Partial integration achieved:** every *Must* test passes (B4, N1–N5, N8–N10, plus B1–B2 if audio is shown).
- **Audio claimed real-time:** A1 and A2 pass. Otherwise say so in the demo and show audio with
  `python3 -m mosaic.dashboard --scenario lecture` as a simulated stand-in, labelled *Simulated*
  (the dashboard's source pill does this automatically).
- **Evidence kept:** the CSV, serial logs and screenshots for every test, ready for the final report.

## 6. Fallbacks

| Problem | Fallback |
|---------|----------|
| Campus Wi-Fi blocks devices | Phone hotspot (already the default above) |
| Node can't reach the PC | Check the PC IP hasn't changed; check the firewall; rebuild with the new IP |
| Audio not ready | Demo sensors + CONFIG + recovery on the real node; show fusion with the `lecture` scenario |
| One Pico fails | Each member keeps a flashed spare; node IDs are set per build, so reflash with the same ID |
