# Classifier port test cases and results

| ID | Method | Expected result |
|---|---|---|
| S2-U03 | Host replay through original/ported classifier | Exact logits, winning class and Q15 probabilities |
| S2-U04 | Actual C inference adapter under replay harness | Wire IDs 1/2/4, reserved slot zero, percent sum 100, Q8 RMS to Q4 |
| S2-U05 | C gate and persistence checks | Low/clipped/stale windows UNKNOWN; two speech windows start TALKING; transient veto |
| INT-05 | Hardware node to PC via existing MQTT owner | Two ordered windows per report, drop counts and confidence configuration respected |
| S2-U06 | Existing PC protocol and S5 tests | All existing cases pass |

Run `py node/testing/subsystem1/test_audio_port.py`. INT-05 remains NOT RUN
until the S4 MQTT bridge and hardware are tested together.

## Results

| Date | ID | Commit | Result | Evidence |
|---|---|---|---|---|
| 2026-11-16 | S2-U03..05 combined replay | `55476b0` | FAIL (harness) | `../subsystem1/logs/2026-11-16_audio-replay.txt`; independent case reused timestamp/state; fixture corrected before rerun |
| 2026-11-16 | S2-U03..05 combined replay | `b2385d8` | PASS | `../subsystem1/logs/2026-11-16_audio-replay-r2.txt`; original/ported logits and probabilities match, adapter and gates pass |
| 2026-11-16 | S2-U06 protocol/S5 regression | `b2385d8` | PASS | `logs/2026-11-16_protocol-s5.txt`; 22 tests pass |
