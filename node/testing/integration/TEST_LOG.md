# Integration — test log

Tests that two or more subsystems work together. Every interface listed in TEAM.md section 5, including every current production interface, must have at least one integration test; the remaining coverage still needs to be defined and recorded. Both owners agree on each test and sign off its result.

See `testing/README.md` for how to run tests and record results.

## Test cases

Define a test here before running it. Test IDs never change.

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| INT-01 | samples flow from S2 to S3 (≥ 5 in 2 s) | IF-01, IF-02 | auto | `subsystem3_test.c` | `[TEST] INT-01 PASS` |
| INT-02 | summary lines flow from S3 to S4 (≥ 2 in 3.5 s) | IF-03 | auto | `subsystem4_test.c` | `[TEST] INT-02 PASS` |
| INT-03 | On-board LED shows connection status | none (shared network task, not a TEAM.md interface) | manual | With Mosquitto and the PC gateway running, flash the `NET=lwip MQTT=1` image and watch boot. Stop Mosquitto, restart it, then switch the hotspot off and back on. Save the USB console and timestamped broker or gateway observations in `logs/` and list a short unlisted video in `videos/README.md` per `testing/README.md`. | At boot, fast blink (4 Hz) then steady on; the slow blink (1 Hz) may last under half a second on a fast network, so check for the `led: slow` console line instead of seeing it. Stopping Mosquitto gives slow blink within 10 s, restarting restores steady on. Hotspot off gives fast blink; hotspot back on restores steady on. After reconnection, confirm a fresh protocol v2 telemetry packet from this node at the broker or gateway; an old MQTT session can read as connected for up to 60 s. Each `led:` line matches the visible pattern. |

INT-03's fresh telemetry check exercises the outbound path only. **Proposed separate
control-path test, not yet run:** after reconnecting, send a valid CONFIG from the PC
to the selected node, then capture the corresponding CONFIG_ACK with matching node ID,
configuration version and OK status at the gateway or in decoded MQTT packets. A
queued HTTP response or a telemetry version alone is not an observed ACK. Alternatively,
test an addressed PING and matching PONG. The owners must agree the test, assign its
unused ID and record the actual result and evidence; this proposal is not a pass.

*Method:* **auto** = `TEST_CHECK` in code, result printed on the console;
**manual** = a person observes the result (LED, scope, meter, phone app…).

## Results

Add a new row for every run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | INT-01 | `abc1234` | | PASS / FAIL | `logs/YYYY-MM-DD_….txt` | |
