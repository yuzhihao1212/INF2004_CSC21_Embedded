# Subsystem 4 — test log

**Subsystem:** Networking and node health (Arif)  ·  **Student ID:** 2500768  ·  **Code:** `app_program/subsystem4/`

See `testing/README.md` for how to run tests and record results.

## Test cases

Define a test here before running it. Test IDs never change.

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| S4-U01 | message buffer max line = S4_SUMMARY_MAX | IF-03 | auto | `subsystem4_test.c` | `[TEST] S4-U01 PASS` |
| S4-U02 | LED pauses and resumes every 6 reports | IF-05 | manual | 1. Flash normal image. 2. Watch LED and console ~20 s. | console shows "LED task paused"/"resumed"; LED stops/starts |
| S4-U03 | Telemetry expiry and reconnect cutoff | S4 MQTT recovery | auto | `subsystem4_test.c` | `[TEST] S4-U03 PASS` |
| S4-U04 | Measure healthy progress before enabling the watchdog | S4 task supervision | manual | Run the default MQTT image under concurrent audio, sensor and reporting load at the shortest and longest supported report periods. Stop the broker, restart it, then cycle Wi-Fi. Save serial output and the largest measured progress gaps. | All four tasks report progress throughout; measured gaps and the chosen timeout margin are recorded. |
| S4-U05 | Watchdog recovery from a local stall | S4 task supervision | manual | Flash a bench build with the timeout validated by S4-U04. After the armed message, suspend one supervised task with a one-shot test hook while the other tasks remain runnable. Remove the hook for post-recovery runs. | Node resets and logs a watchdog timer reset reason on the next boot. |
| S4-U06 | Broker and Wi-Fi recovery with a validated watchdog | S4 MQTT recovery and task supervision | manual | With the watchdog armed, take the broker down for longer than the timeout, restore it, then repeat for Wi-Fi. Record the serial and gateway logs and compare sender timestamps across reconnect. | No reset; sensing progress continues; gateway becomes live on the first fresh report and can confirm retained CONFIG. |

*Method:* **auto** = `TEST_CHECK` in code, result printed on the console;
**manual** = a person observes the result (LED, scope, meter, phone app…).

## Results

Add a new row for every run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | S4-U01 | `abc1234` | | PASS / FAIL | `logs/YYYY-MM-DD_….txt` | |

## Status at hand-in (25 Nov 2026)

No result for the tests above is recorded in this repository. The hardware was
returned after the final demo on 25 Nov 2026, so they cannot be run now. If you
have a saved console log from an earlier run, add it to `logs/` and add a row.
The watchdog stays switched off (`S4_WATCHDOG_TIMEOUT_MS` is 0) because S4-U04 to S4-U06 were never run.
The gateway side of the MQTT recovery is covered by `pc/tests/test_mqtt.py`.
