# Week 13 evidence plan

What we still need to show the assessors, who owns it, and what "done" looks like.
The CSC21 tracker in `change_requirement_csc21.md` lists *what* the brief asks for; this
page is the plan to get it. Status on 16 Nov 2026: the PC side is done and tested, but the
node has no measured evidence yet. All 21 Week 10 hardware results are blank, and audio
isn't linked into the node build (`MOSAIC_NODE_AUDIO_SOURCES` is empty).

**Rule for every item:** a number only counts if it comes from a log or file committed to
`docs/evidence/<item>/`, with the commit hash of the firmware that produced it. No log, no
claim. That's also what the "Record versions" rule in our process asks for.

Dates are proposals until the team agrees them in the group chat.

## 1. Audio on the node (blocks most of the rest)

| # | Step | Owner | Done when | Proposed date |
|---|------|-------|-----------|---------------|
| 1a | Audio capture and DSP as a micro T-Kernel task in `node/app_program/subsystem1/` | Moe, paired with ZhiHao | The `make TEST=1` image logs one processed window every 500 ms; subsystem 1 tests pass in `node/testing/subsystem1/` | Wed 18 Nov |
| 1b | int8 classifier in `subsystem2/` on those windows, posting each one with `s5_post_audio_window()` (IF-10) | Darius | Week 10 test B3 passes: inference p99 ≤ 100 ms, no floats in the per-window path; reports carry `audio_window_count` = 2 | Fri 20 Nov |
| 1c | Same build on four Picos, reaching the PC through subsystem 4's MQTT link | Arif, ZhiHao | Four nodes **Online** on the dashboard (`--mqtt`), each with its own ID | Sun 22 Nov |

*Updated 16 Nov:* the node moved to the micro T-Kernel template in `node/` (μT-Kernel is a
hard requirement), so these steps target its subsystem folders instead of the FreeRTOS
`mosaic_node_rtos` build. See `docs/decision-log.md`.

If 1a slips past the agreed date, the team decides together who picks it up and we log
that in `decision-log.md`. Nobody takes over someone's part without that.

## 2. Measured resource budget (one page, `docs/resource_budget.md`)

| Number | How we get it | Owner |
|--------|---------------|-------|
| DSP time per 500 ms window (mean, p99, max) | `audio_benchmark`, ≥ 100 windows (test B2) | Moe |
| Inference time per window | Darius's timing build (test B3) | Darius |
| DSP + inference with Wi-Fi active | 10-min run, `audio_overruns` stays 0 (test A2) | Moe |
| Headroom against the 500 ms budget | Computed from the three rows above | Moe |
| Flash and RAM used | `firmware/tools/fw_budget.py`, run by CI on every PR, now including the micro T-Kernel node in `node/`. Template images measured locally on 16 Nov (`docs/resource_budget.md`); the final figure comes once our subsystems are in `node/app_program/` | ZhiHao |
| Stack high-water mark per task, min free heap | Already printed every 10 s by the RTOS health task; take the worst value from the soak log | Arif |
| CPU load per task | Not measured yet. Turn on FreeRTOS run-time stats (`configGENERATE_RUN_TIME_STATS` with the 1 MHz timer) and print `vTaskGetRunTimeStats` | Arif |
| No soft-float helpers in the `.elf` | `fw_budget.py` lists every float call in our code by function. 16 Nov: only `audio_dsp_init` (start-up tables) and the benchmark's printing. Moe decides whether to precompute the tables as `const` | Moe, Darius |

## 3. Accuracy you can show

| Comparison | Method | Owner |
|------------|--------|-------|
| Fixed-point DSP vs float | Same recorded windows through both versions; max and mean error per feature, stated margin | Moe |
| int8 vs float classifier | Same test set; confusion matrix for each, agreement %, stated margin | Darius |
| Classroom state on real data | Scripted 7–8 min lesson in a real room with four nodes, scored by `python3 -m mosaic.evaluate --expected` against labels a person writes while watching (not the script-derived `lecture_expected.csv`) | ZhiHao |
| Integer vs float fusion | Done on simulated scenarios (`test_integer_accuracy.py`); rerun on the real-room capture | ZhiHao |

## 4. Reliability and the fault demo

| Item | Method | Owner |
|------|--------|-------|
| Soak | Four nodes for 1 h on the hotspot. Report loss, reboots, RTT p95 and overruns from the evaluator's summary, and each reboot's reset reason from the serial log. Pass: no reboots, loss < 1 % | Arif, ZhiHao |
| Wi-Fi drop recovery | Week 10 test N9 | Arif |
| Reboot recovery and CONFIG re-send | Week 10 test N8 | ZhiHao |
| CONFIG round trip | `mosaic.evaluate` now reports it (request → applied, and last send → ACK). Run 20 CONFIGs during a real-node capture | ZhiHao |
| Live fault demo (Week 13) | Unplug one node in front of the assessors: its area shows *No signal*, the rest of the room keeps working, it comes back on its own when plugged in | ZhiHao runs, Arif backs up |

## 5. Write-ups

- **Numeric representation rows** still marked To do: DSP Q-formats (Moe), int8 scales and
  zero points (Darius).
- **Environmental and occupancy conversions (Kendrick):** documented in
  `docs/environment_numeric_representation.md`; hardware comparison and integrated
  evidence remain pending. See `node/testing/subsystem3/HARDWARE_EVIDENCE.md`.
- **Microphone choice:** the brief lists an I²S MEMS microphone; we use an analog one on the
  ADC. One paragraph on why, with the B1 speech-vs-silence measurement as support (Darius).
- **Sensor accuracy:** B4/N3 against a reference thermometer (Kendrick).

## What we're not doing

More dashboard work. It's finished, and further UI polish won't change how the embedded
side is judged.
