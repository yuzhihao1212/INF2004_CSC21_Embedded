# Subsystem 3 — test log

**Subsystem:** Environmental sensing (Kendrick)  ·  **Student ID:** <student ID>  ·  **Code:** `app_program/subsystem3/`

See `testing/README.md` for how to run tests and record results.

## Test cases

Define a test here before running it. Test IDs never change.

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| S3-U01 | statistics self-consistent (min ≤ max, 0..100) | | auto | `subsystem3_test.c` | `[TEST] S3-U01 PASS` |
| S3-U02 | DHT and CO2 decoding, checksums, validity and timestamp rollover | environment data contract | host | `host/environment_host_test.c` | exits successfully |
| S3-U03 | ACD1100 warm-up, request timing, responses and timeouts | environment data contract | host | `host/acd1100_host_test.c` | exits successfully |
| S3-U04 | S3 validity mapping into S5 telemetry | IF-08 | host | `host/s5_environment_host_test.c` | exits successfully |
| S3-U05 | PIR sampling, motion and S5 reporting | IF-09 | manual | see `ENVIRONMENT_MIGRATION.md`; requires Pico W and PIR | motion counts reach telemetry without interrupting example traffic |

*Method:* **auto** = `TEST_CHECK` in code, result printed on the console;
**manual** = a person observes the result (LED, scope, meter, phone app…).

Continuation cases (defined before running):

- S3-U06: service scheduling, config changes/rejection, future time and wrap; host `service_host_test.c`, expect minimum spacing and last-good config.
- S3-U07: actual S3 calls to mocked S5 public API, timeout/error handling, PIR counts, stale expiry and sensor isolation; host, expect no fabricated samples or duplicate batches.
- S3-U08: polled UART transport with deterministic FIFO responses/errors; host, expect bounded draining, framing rejection, warm-up and timeouts.
- S3-U09: DHT capture completion/timeout/bus-error/abort recovery with hardware doubles, checksum rejection and formatter tiny/zero buffers; host, expect safe reuse and invalid flags.
- S3-U10: PIO source/header reproducibility; run `host/check_pio.py <pioasm>`; expect identical RP2040 instructions and wrap bounds.
- S3-U11: target environment task execution; `TEST=1`, expect a positive task ID and progress counter to advance during a 500 ms delay (requires running image for runtime result).
- S3-U12: actual UART1 register driver using mocked MMIO; host, verify 1200 8N1, only claimed registers, nonblocking FIFO and error handling.
- S3-U13: cross-build UART/no-Wi-Fi SMP=0 TEST=0; expect ELF/UF2 generation.
- S3-U14: cross-build UART/no-Wi-Fi SMP=0 TEST=1; expect ELF/UF2 generation.
- S3-U15: cross-build UART/no-Wi-Fi SMP=1 TEST=0; expect ELF/UF2 generation.
- S3-U16: cross-build UART/no-Wi-Fi SMP=1 TEST=1; expect ELF/UF2 generation.
- S3-U17: strict Arm compile of S3, `-Wall -Wextra -Werror`, no-Wi-Fi profile; expect no diagnostics.
- S3-U18: Wi-Fi/MQTT build prerequisite check; requires actual SDK 2.2/2.3, not template's hardcoded version header.
- S3-U19: simulated task creation/start failures, retries, idempotence, and unexpected exit; host `startup_host_test.c`; expect no duplicate tasks or restart after exit.
- S3-U20: simulated execution of the real environment task loop, sensor failure, progress and active-capture cleanup on exit; host `service_host_test.c`; expect progress and continued PIR reporting.
- S3-U21: actual DHT hardware-boundary source against SDK register doubles; simulate ABORT cleared while BUSY stays high, then BUSY clears; expect no early IRQ/FIFO cleanup or reuse.
- S3-U22: hold simulated DMA BUSY across many service iterations; expect PIR and S5 service to continue, no new capture, and timeout rather than stale success after retirement.

- S3-U23: host, test-only counters and snapshot lock behavior using sensor/kernel doubles; `host/run.ps1` must exit successfully. This is not hardware evidence.
- S3-U24: **manual target**, valid DHT acquisition/checksum. S3 hardware guide, steps 1–4; `dok` rises, `ds=1`, and `flags & 3 == 3`.
- S3-U25: **manual target**, CO2 warm-up then response. Start from cold boot; before 120 s `warm=0`, CO2 invalid; after 120 s `warm=1`, `cok` rises and CO2 valid.
- S3-U26: **manual target**, PIR controlled stillness and motion; sample count rises in both intervals, motion count rises while moving, and current motion tracks activity subject to sensor hold time.
- S3-U27: **manual target**, DHT disconnect/reconnect; timeout/failure and invalidity appear, then a valid capture and recovery count after reconnection.
- S3-U28: **manual target**, DHT unavailable isolation; task progress and PIR sample counts continue, and CO2 continues after warm-up.
- S3-U29: **manual target**, timeout retirement. Disconnect DATA and inspect `dto`, `da`, `stop`, `cap` and, with nonintrusive trace if available, DMA BUSY; no new capture until retirement. A disconnect alone cannot demonstrate prolonged BUSY; that separate condition remains host-simulated unless actually observed.
- S3-U30: **manual target**, fixed-point values, status and validity; compare valid decimal values to a reference, then disconnect to check invalidation without treating retained values as current.
- S3-U31: **manual target**, B4/N3 five-minute reference comparison and PC warm-up display; use `HARDWARE_EVIDENCE.md`, retain timestamped logs/photos and screenshot.
- S3-U32: host, test-only observer startup returns before observation; check its priority, affinity, stack request, 65 iterations, self-delete and creation/start failure cleanup using kernel doubles. Target scheduling and stack headroom remain unverified.

## Results

Add a new row for every run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | S3-U01 | `abc1234` | | PASS / FAIL | `logs/YYYY-MM-DD_….txt` | |
| 2026-11-16 | S3-U02 | `986510f` + uncommitted changes | Codex | provisional PASS | `logs/2026-11-16_host.txt` | Host logic only; repeat on a committed revision. |
| 2026-11-16 | S3-U03 | `986510f` + uncommitted changes | Codex | provisional PASS | `logs/2026-11-16_host.txt` | Transport-independent state machine only. |
| 2026-11-16 | S3-U04 | `986510f` + uncommitted changes | Codex | provisional PASS | `logs/2026-11-16_host.txt` | S5 pure telemetry builder, not MQTT. |

## Continuation results (uncommitted, provisional)

Commit: `986510ff767734cb6edcf42504b29f001fa270b6` plus working changes. Tester: Codex. Date: 2026-11-16. Source hashes: `logs/2026-11-16_source_manifest.txt`.

- S3-U02: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U03: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U04: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U06: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U07: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U08: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U09: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U12: provisional PASS; `logs/2026-11-16_continuation_host_final.txt`. Host only.
- S3-U10: provisional PASS; `logs/2026-11-16_pio_check.txt`. Installed pioasm reproduction.
- S3-U13: provisional PASS; `logs/20261116_220704_uart_smp0_test0.txt`. Cross-build only; no sensor execution.
- S3-U14: provisional PASS; `logs/20261116_220704_uart_smp0_test1.txt`. Cross-build only; no sensor execution.
- S3-U15: provisional PASS; `logs/20261116_220704_uart_smp1_test0.txt`. Cross-build only; no sensor execution.
- S3-U16: provisional PASS; `logs/20261116_220704_uart_smp1_test1.txt`. Cross-build only; no sensor execution.
- S3-U17: provisional PASS; `logs/2026-11-16_strict_compile.txt`. Wi-Fi DHT hardware branch excluded.
- S3-U18: BLOCKED; `logs/2026-11-16_wifi_prerequisite.txt`. SDK not configured; only unsupported SDK 1.5.1 installed.
- S3-U05, S3-U11, S3-U01 and INT-01 target execution: NOT RUN; no board run.

Earlier continuation build/test logs are retained. The final logs above supersede their code snapshots without editing prior evidence. The user prohibited committing; rerun after a normal team commit for formal template-compliant records.

## 2026-11-17 targeted correctness results (uncommitted, provisional)

Base commit: `986510ff767734cb6edcf42504b29f001fa270b6` plus working-tree
changes. Tester: Codex. The current S3 source and host-test hashes are in
`logs/2026-11-17_correctness_source_manifest.txt`. Repeat on a committed
revision; none of the following is a Pico W hardware result.

- S3-U02, U03, U04, U06–U09, U12, U19–U22: provisional PASS (host,
  with the documented kernel, sensor or SDK register doubles);
  `logs/2026-11-17_correctness_host_u22.txt`.
- S3-U10: provisional PASS, installed pioasm 1.5.1; `logs/2026-11-17_correctness_pio.txt`.
- S3-U13, U14, U15, U16: provisional PASS, UART/no-Wi-Fi cross-builds;
  `logs/20261117_093727_uart_smp0_test0.txt`,
  `logs/20261117_093727_uart_smp0_test1.txt`,
  `logs/20261117_093727_uart_smp1_test0.txt`, and
  `logs/20261117_093727_uart_smp1_test1.txt` respectively.
- S3-U17: provisional PASS, strict Arm compilation with the Wi-Fi hardware
  branch excluded; `logs/2026-11-17_correctness_arm_strict.txt`.
- S3-U11, S3-U01, S3-U05 and INT-01 on target: NOT RUN. The host task-loop
  test does not establish real kernel scheduling or hardware behavior.
- Wi-Fi/MQTT cross-build: NOT RUN; supported SDK 2.2/2.3 unavailable. Its
  SDK-dependent DHT hardware path and radio coexistence remain unverified.

## 2026-11-18 diagnostic host verification (uncommitted, provisional)

Base `c6a33c85c016d3625919f935f2e6c6e04423f953` plus the diagnostic patch; tester: Codex. S3-U23 and the existing host suite and S3-U10 passed with simulated hardware; log `logs/2026-11-18_diagnostic_host.txt`. All on-target cases above remain unperformed. Repeat and record results against a committed revision for formal evidence.

Cross-builds: UART/no-Wi-Fi SMP 0/1 with TEST 0/1 and SMP 1 USB/Wi-Fi/lwIP/MQTT with TEST 0/1 passed; `logs/2026-11-18_diagnostic_builds.txt` contains build-log excerpts. They do not establish runtime behavior.

## 2026-11-18 diagnostic review (uncommitted, provisional)

Base `c6a33c85c016d3625919f935f2e6c6e04423f953` plus the reviewed working tree; tester: Codex. S3-U23 and S3-U32 and the existing host suite passed with doubles; S3-U10 passed with pioasm 1.5.1. The saved output and working-tree source hashes are in `logs/2026-11-18_review_host.txt`. These are simulations, not Pico W measurements.

S3-U13–U16: UART/no-Wi-Fi cross-builds passed for SMP 0/1 and TEST 0/1; logs `logs/20261118_163220_uart_smp0_test0.txt`, `logs/20261118_163220_uart_smp0_test1.txt`, `logs/20261118_163220_uart_smp1_test0.txt`, and `logs/20261118_163220_uart_smp1_test1.txt`. S3-U17: strict Arm compilation of S3 with TEST 0/1, UART/no Wi-Fi, passed; `logs/2026-11-18_review_strict.txt`.

SMP 1 USB/Wi-Fi/lwIP/MQTT cross-builds passed with Pico SDK 2.2.0 and TEST 0/1 using temporary example credentials; `logs/2026-11-18_review_wifi_test0.txt` and `logs/2026-11-18_review_wifi_test1.txt`. These builds do not establish radio, sensor, scheduler or stack behavior. All on-target cases remain unperformed; repeat against a committed revision for formal evidence.

## 2026-11-21 assessment review (uncommitted, provisional)

Base `3a8f6ef5260fe7892ca1331495b12d5f19b90380` plus the S3 diagnostic changes; tester: Codex. Source hashes for the changed S3 and test files: `logs/2026-11-21_source_manifest.txt`. These checks do not replace a run of a committed revision. No hardware was connected or tested.

- S3-U02–U04, U06–U09, U12, U19–U23 and U32: PASS in host logic and doubles, including the new checksum and accepted-post counters; `logs/2026-11-21_assessment_host.txt`.
- S3-U10: PASS, installed pioasm 1.5.1; `logs/2026-11-21_assessment_pio.txt`.
- S3-U13–U16: PASS cross-build, UART/no Wi-Fi, SMP 0/1 and TEST 0/1 respectively; `logs/20261121_083959_uart_smp0_test0.txt`, `logs/20261121_083959_uart_smp0_test1.txt`, `logs/20261121_083959_uart_smp1_test0.txt`, `logs/20261121_083959_uart_smp1_test1.txt`. These profiles explicitly do not provide DHT acquisition.
- S3-U18: BLOCKED on this machine, supported SDK not configured; `logs/2026-11-21_wifi_prerequisite.txt`. The integrated Wi-Fi/MQTT profile has not been rebuilt in this review.
- S3-U01, U05, U11, U24–U31 and concurrent hardware operation: NOT RUN. See `HARDWARE_EVIDENCE.md` for the remaining measurements.

Static review: the environmental task delays each iteration and polls DMA retirement without spinning. The retained example `consumer_task` blocks on its mailbox in normal operation, but immediately retries and prints if `tk_rcv_mbx` repeatedly fails; that exceptional path can loop without a delay. It is separate from the environmental task and remains unresolved. S3 objects from the SMP=1 TEST=1 no-Wi-Fi build had no undefined soft-float arithmetic helpers; that does not audit the SDK-dependent Wi-Fi branch or prove target execution.

The earlier S3 results above cite historical logs that are not present in this checkout. They remain unchanged as historical records; locate those original logs or repeat the tests before relying on them as assessment evidence.
