# Subsystem 5 — test log

**Subsystem:** Node config and telemetry  ·  **Student ID:**  ·  **Code:** `app_program/subsystem5/`

See `testing/README.md` for recording on-target results. No Pico has been flashed
or tested for this port. Results stay empty until hardware evidence is saved.

## Test cases

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| S5-U01 | Default configuration | Protocol v2 defaults | auto | `subsystem5_test.c`, local state | Version 0; report 1000 ms; all default fields match |
| S5-U02 | Valid CONFIG | IF-06/07/12 | auto | Apply version 2 with changed intervals, gain, mode and threshold | ACK OK, echoed version; full snapshot applied |
| S5-U03 | Invalid CONFIG | IF-06/07 | auto | Report interval 50 ms | ACK INVALID_VALUE; config unchanged |
| S5-U04 | Version ordering and retries | IF-06/07 | auto | Older version, then same-version retry with changed values | STALE_VERSION then OK and reapply |
| S5-U05 | Invalid control boundaries | IF-06 | auto | Wrong node, magic, version, length, payload size, type; unaligned buffers | Ignored without reply/state change; valid unaligned CONFIG works |
| S5-U06 | PING/PONG | IF-06/07 | auto | Send 64-bit `pc_time_us` | PONG echoes all 8 bytes; current node time |
| S5-U07 | Shared sequence and first flag | IF-07 | auto | Drop first telemetry, accept next, accept ACK, build again | Drops consume no seq; first flag clears only on accepted telemetry |
| S5-U08 | PIR sampling | IF-09 | auto | Post 3 active of 10; build twice | 30 percent valid, then zero/invalid |
| S5-U09 | Environment freshness | IF-08 | auto | Build at age 6000 and 6001 ms; cross uint32 clock wrap | Fresh at 6000; expired bits and readings zero at 6001; wrap handled |
| S5-U10 | Audio batching and validation | IF-10 | auto | Post 3 windows, reject reserved class and probability, build twice | Newest 2 windows, overrun +1; sequence 3; maxima cleared on take |
| S5-U11 | Audio lost on TX failure | IF-07/10 | auto | Drop telemetry carrying 2 windows | Overruns +2; seq unchanged; first flag retained |
| S5-U12 | Live CONFIG/ACK | IF-06/07/12 | auto | Drain TX; enqueue version 1 default CONFIG; skip telemetry while reading TX | ACK OK and applied snapshot within 200 ms |
| S5-U13 | Target self-tests and console evidence | All S5 interfaces | manual | Run `make TEST=1 -j8`, flash that image, save USB console to a new dated file in `logs/`; never run this step automatically | S5-U01…U12 PASS, node ID once, CONFIG applied line; save commit and log in Results |

S5-U12 sends CONFIG version 1; once S4 delivers the PC's retained CONFIG with a version above 1 before the tests run, U12 will get STALE_VERSION, so the test must then send a version above the applied one.

The host runner `host/s5_protocol_host_test.c` uses the same pure cases U01…U11
from `host/s5_cases.h`, adds counter saturation, capture gaps, malformed audio,
health and sequence-wrap checks, and emits TELEMETRY + CONFIG_ACK bytes for
`pc/tests/test_node_s5.py`. Host execution does **not** establish U12 or U13.
Include `subsystem5.h` before `app.h`/other subsystem headers when using the
protocol alongside kernel APIs; this uses the kernel's `PROHIBIT_DEF_SIZE_T`
guard, like the template's `sys_arch.c`.

## Host runs

Runs of the pure S5 logic compiled for a PC, not on a Pico W. They check the
protocol code and C/Python byte agreement, but they are not hardware evidence:
U12 (live CONFIG/ACK) and U13 (target self-tests) need a flashed board. Add a
new row for every host run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| 2026-11-18 | S5-U01…U11 + edge cases | `bf3c7f9` | ZhiHao (run by Claude Code) | PASS (host) | `logs/2026-11-18_host.txt` | `host/s5_protocol_host_test.c` built with Apple clang 17, `-Wall -Wextra -Werror`, exit 0; 84 bytes out; `pc/tests/test_node_s5.py` decodes them: OK. U12, U13 not run. |

## Results

Add a new row for every hardware run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
