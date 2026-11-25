# System — test log

Tests of the complete product against its requirements, run on the final hardware set-up. Run the full set before every demo and before hand-in.

See `testing/README.md` for how to run tests and record results.

## Test cases

Define a test here before running it. Test IDs never change.

These six cases are the scenarios planned for the final demo: four nodes
(reference node at the lecturer's position, Nodes 2 to 4 in the front, middle
and back rows), a Mosquitto broker and the dashboard on one laptop, all on the
demo hotspot. They were written into this log on 25 Nov 2026, after the demo,
from the demo plan: see "How to read these results" below.

| ID | What is tested | Requirement / interface | Method | Steps / how | Expected result |
|---|---|---|---|---|---|
| SYS-01 | Four nodes come online | Node start-up, Wi-Fi and MQTT link (S4), retained CONFIG delivery (S5), node status on the PC | manual | 1. Start Mosquitto and the dashboard. 2. Power on all four nodes. 3. Watch each on-board LED and the dashboard. | Each LED goes from fast blink (no Wi-Fi) to slow blink (Wi-Fi, no broker) to steady. All four zones show live on the dashboard |
| SYS-02 | The lecturer speaks at the reference node | Audio capture and DSP (S1), classifier (S2), telemetry (S5), lecturer rule in fusion | manual | 1. Speak at the reference node. 2. Watch its zone on the dashboard. | Within about 20 s the reference zone changes to "Lecturer speaking" |
| SYS-03 | A student talks at Node 2 | S1, S2, S5, lecturer-reference comparison on the PC | manual | 1. Talk at Node 2. 2. Watch all zones. | Within about 20 s only Node 2 changes to "Talking". Nodes 3 and 4 stay "Settled" |
| SYS-04 | The room goes quiet | S1, S2, per-node noise floor and persistence on the PC | manual | 1. Everyone stops talking. 2. Watch all zones. | Within about 20 s every zone returns to "Settled" |
| SYS-05 | Change a setting from the dashboard | CONFIG, CONFIG_ACK (S5), MQTT config topic (S4), gateway delivery | manual | 1. On the dashboard, switch Class type from Lecture to Group work. 2. Watch the line under the buttons. | "Group work: all 4 sensors updated" appears: all four nodes acknowledged the CONFIG |
| SYS-06 | Unplug a node | Node status tracking on the PC, per-zone failure handling in fusion, node reconnect (S4) | manual | 1. Unplug Node 3. 2. Watch the dashboard for 15 s. 3. Plug it back in. | Node 3 shows delayed after 3 missed reports and not connected after 10 s. Its zone shows no data while the other zones carry on. Plugged back in, it returns |

*Method:* **auto** = `TEST_CHECK` in code, result printed on the console;
**manual** = a person observes the result (LED, scope, meter, phone app…).

## Results

Add a new row for every run. Never edit or delete old rows.

| Date | Test ID | Commit | Tester | Result | Log / evidence | Notes |
|---|---|---|---|---|---|---|
| 2026-11-25 | SYS-01, SYS-02, SYS-03, SYS-04, SYS-06 | `2ec7d6e` (`demo` branch), as reported by the team | Whole team, final demo | Mostly as expected, with some inconsistent results | None saved: observed live in the final demo, no recording | The team reports that the scenarios mostly worked, and that some results were inconsistent because of the room and other factors outside its control. Which scenarios were inconsistent, and how, was not written down at the time. Do not read this row as five separate passes |
| 2026-11-25 | SYS-05 | `2ec7d6e` | | NOT RUN | | The team decided before the demo started not to show this scenario. CONFIG delivery and acknowledgement are covered on the host by S5-U02 to S5-U04 and `pc/tests/test_gateway.py`, and on simulated nodes over MQTT by `pc/tests/test_mqtt.py`; there is no recorded run on four real nodes |

## How to read these results

- **One run, no saved evidence.** The final demo on 25 Nov 2026 is the only run
  of these scenarios on the final code. Nobody recorded it and no console or
  dashboard log was saved, so the row above is the team's report, not a
  measurement.
- **The test cases were written down after the run.** They come from the demo
  plan, which existed before the demo, but this log did not hold them then. The
  testing rules ask for the definition first.
- **The commit is as reported.** The nodes were flashed from the `demo` branch
  at `2ec7d6e`, with the Wi-Fi settings and node IDs in local files that Git
  ignores. That build was not checked against the repository afterwards.
- **What no scenario covers.** None of the six exercises the environment
  sensors end to end (temperature, humidity, CO2, motion on the dashboard), the
  excessive-noise level, or recovery from a broker or Wi-Fi outage. The earlier
  four-node session on 20 Nov, in `../integration/logs/2026-11-20-four-node-session.md`,
  recorded real audio telemetry but no valid temperature, humidity or CO2.
- **No further runs are possible.** The hardware was returned after the demo.
  What can still be checked without it is in each subsystem's log: the host
  tests run on the hand-in code by `node/testing/run_host_tests.sh`.
