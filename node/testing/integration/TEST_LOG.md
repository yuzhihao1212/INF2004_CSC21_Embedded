# Integration — test log

Tests that two or more subsystems work together. There is one test (or more) for every interface listed in TEAM.md section 5. Both owners agree on the test and sign off the result.

See `testing/README.md` for how to run tests and record results.

## Test cases

Define a test here before running it. Test IDs never change.

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| INT-01 | samples flow from S2 to S3 (≥ 5 in 2 s) | IF-01, IF-02 | auto | `subsystem3_test.c` | `[TEST] INT-01 PASS` |
| INT-02 | summary lines flow from S3 to S4 (≥ 2 in 3.5 s) | IF-03 | auto | `subsystem4_test.c` | `[TEST] INT-02 PASS` |
| INT-03 | On-board LED shows connection status | none (shared network task, not a TEAM.md interface) | manual | With Mosquitto running, flash the `NET=lwip MQTT=1` image and watch boot. Stop Mosquitto, restart it, then switch the hotspot off and back on. Save the USB console output in `logs/` and list a short unlisted video in `videos/README.md` per `testing/README.md`. | At boot, fast blink (4 Hz) then steady on; the slow blink (1 Hz) may last under half a second on a fast network, so check for the `led: slow` console line instead of seeing it. Stopping Mosquitto gives slow blink within 10 s, restarting restores steady on. Hotspot off gives fast blink; hotspot back on restores steady on, and the log must then show a new heartbeat publish and its echo (an old MQTT session can read as connected for up to 60 s). Each `led:` line matches the visible pattern. |

*Method:* **auto** = `TEST_CHECK` in code, result printed on the console;
**manual** = a person observes the result (LED, scope, meter, phone app…).

## Results

Add a new row for every run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | INT-01 | `abc1234` | | PASS / FAIL | `logs/YYYY-MM-DD_….txt` | |
