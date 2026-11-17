# Subsystem 3 — test log

**Subsystem:** Consumer (example)  ·  **Student ID:** <student ID>  ·  **Code:** `app_program/subsystem3/`

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
