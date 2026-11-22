# Four-node integration session — 20 November 2026

Recorded at approximately 15:57 Singapore time, based on the operator's reports
and screenshots in the working session. This is an observation, not a formal
test pass or a substitute for board console logs.

- Branch at recording: `arif/utk-network`.
- Base commit: `6123d584438e239ca1f800b76b6ae01b438363c5`. The workspace
  contained uncommitted changes when the firmware was built, so this hash alone
  does not identify the firmware exactly.
- The operator's dashboard screenshot showed sensors 1–4 as Working, with an
  audio classification for each. Temperature, humidity, and CO2 were not
  available. This does not validate sensor accuracy or long-run connectivity.
- The operator reported that calibration had completed. Per-zone calibration
  results and the time of completion were not independently captured here.
- A local experimental PC fusion noise floor was configured for node 2. The
  reported dashboard state is conditional on the active dashboard configuration;
  verify that configuration in the board run.
- Dashboard screenshot saved as `docs/evidence/four-real-nodes-online.png`.
- MQTT telemetry capture started in a separate VS Code terminal at about 15:59
  Singapore time, to `node/testing/integration/logs/2026-11-20-four-node-telemetry.csv`.
  It includes reports observed from all four node IDs. This is gateway-side
  telemetry, not each board's USB serial console log.
- Per-board serial logs, build identification including the uncommitted diff,
  and subsystem test-log entries remain to be collected. Do not mark the
  four-node functional tests as passed based on this observation.

## Lecturer-only observation

- Operator indicated start at 16:07:50 Singapore time; the intended 30-second
  window was 16:07:50–16:08:20.
- Gateway-side per-window telemetry for that interval is saved as
  `2026-11-20-lecturer-only-160750.csv`: node 1: 60 windows, node 2: 60,
  node 3: 60, node 4: 62. This is not per-board USB serial output.
- An operator-provided dashboard image showed Lecturer speaking, and front,
  middle and back rows Settled at the captured instant. It does not establish
  those states persisted for the whole interval. Screenshot:
  `docs/evidence/lecturer-only-four-nodes.png`.

## Audio stopped after lecturer playback

- The operator reported the lecturer area initially continued to show
  Lecturer speaking after playback stopped, then returned to Settled after
  roughly one minute. Exact start and transition timestamps were not supplied;
  this is an approximate observation, not an instrumented latency measurement.
- Whether all student areas stayed Settled throughout this period has not been
  established, so this is not a completed all-quiet functional test.

## Quiet-room observation starting 16:49:12

- Operator reported quiet began at 16:49:12; the planned quiet test interval
  was 16:49:12–16:49:42. Operator reported the visual showed Settled at
  16:51:19, 127 seconds after the reported start; the relevant area and
  whether silence continued beyond the first 30 seconds require confirmation.
- Gateway telemetry from 16:49:12 through 16:51:19 is saved in
  `2026-11-20-quiet-164912.csv`, 256 windows per node. In the first 30
  seconds, the raw class was SPEECH in 51/60 node-1 windows, 27/60 node-2,
  9/60 node-3 and 12/60 node-4. Assuming the room was silent, these are
  false speech labels, not an accuracy measurement or proof of a cause.
- Visual states for every zone during the first 30 seconds were not recorded.

## Node 1 serial diagnostics after reconnect

- `/dev/cu.usbmodemMTK3PICO1` disappeared when the operator unplugged the
  lecturer reference Pico and reappeared on reconnection. A roughly 12-second
  serial capture was saved as `2026-11-20-node1-quiet-serial.txt` after asking
  the operator to keep the room quiet.
- In the printed sample windows, `clipped=0`, while the model repeatedly
  reported 99–100% speech and TALKING. ADC minima/maxima were approximately
  1954–2155; raw AC RMS was approximately 22–30 ADC units. This is evidence
  of false speech if the room was quiet, but does not establish its cause.
- The reported capture time was approximately 11.7 ms for a nominal 500 ms
  window; the timer scale issue remains unresolved. Capture is a serial
  diagnostic, not a quantified accuracy or electrical-interference test.

## Node 1 PC quiet-gate trial

- Dashboard restarted with `/tmp/mosaic-node1-quiet-trial.json`: node 1 floor
  272 Q12.4 (17 filtered ADC units); node 2 floor 80 Q12.4 (5 units).
- Operator reported all areas Settled during quiet and the lecturer area
  showed Lecturer speaking during playback. Exact times and scenario-specific
  evidence were not recorded; this is a preliminary observation, not proof of
  reliable quiet detection or of sensitivity to soft speech.
- This PC-side trial leaves raw node classifier telemetry unchanged and can
  suppress quiet real speech; it has not fixed the underlying false detection.

## Three concurrent sources, 17:33

- Operator reported all three sources started at 17:33:55; at 17:34:10 the
  lecturer, Node 2 and Node 4 visuals updated (approximately 15 seconds).
  The exact student source positions and displayed labels need confirmation.
- The dashboard was running the 17-unit Node 1 and 5-unit Node 2 trial floors.
- Gateway telemetry for 17:33:55–17:34:12 is saved as
  `2026-11-20-three-speakers-173355.csv`, 34 windows per node. This is not
  per-board USB serial evidence, and the visual timing is user-observed.

## Three concurrent sources after main update, 17:50

- After updating the working branch to `1448c71` and reflashing, the operator
  reported three audio sources starting at 17:50:48; the middle and back row
  visuals changed at 17:51:10 (approximately 22 seconds). The supplied image
  shows Lecturer speaking, middle/back Talking, and front Settled.
- Operator reported all audio stopped at 17:52:01 and the visual changed at
  17:52:21 (approximately 20 seconds). The supplied image shows all areas
  Settled. Times are user-observed, not instrumented latency measurements.
- Gateway telemetry for 17:50:48–17:52:22 is saved in
  `2026-11-20-updated-three-sources-175048.csv` (188 windows per node). The
  running dashboard and active fusion config at this interval require
  confirmation. The source tree still includes uncommitted modifications.

## Student speech near node 2

- Operator reported student speech between 16:11:26 and 16:12:10 Singapore
  time; telemetry excerpt: `2026-11-20-node2-speech-161126.csv`.
- 88 windows were received per node; raw node 2 classes included 76 speech,
  6 transient and 6 unknown. Other microphones also reported speech; raw
  classes do not distinguish lecturer speech from student speech.
- Operator-provided dashboard image showed lecturer speaking, front rows
  Talking, and middle and back rows Settled at the captured instant. Screenshot:
  `docs/evidence/node2-talking.png`.
- Operator reported front rows changed to Settled at 16:14:50, supported by
  a dashboard image showing lecturer speaking and all student areas Settled.
  The operator later clarified student audio stopped approximately five
  seconds before this change while the lecturer continued. This is an
  approximate operator observation, not an instrumented latency measurement;
  its relationship to the earlier 16:12:10 interval is not established.
  The image still needs to be saved in `docs/evidence/`.

## Student speech near node 3

- Operator reported student speech started at 16:20:57; middle rows changed
  to Talking at 16:21:12 (approximately 15 seconds).
- Student audio stopped at 16:21:58; the operator confirmed middle rows returned
  to Settled at 16:22:17 (approximately 19 seconds).
- The submitted dashboard image shows lecturer speaking, middle rows Talking,
  and front/back rows Settled. Screenshot: `docs/evidence/node3-talking.png`.
- Gateway telemetry from 16:20:57 to 16:22:18 is saved in
  `2026-11-20-node3-speech-162057.csv` (162 windows per node). Timings are
  operator observations, not instrumented latency measurements.

## Student speech near node 4

- Assuming times are 16:31 and 16:32 Singapore time: operator reported student
  speech starting 16:31:00 and back rows changing to Talking at 16:31:18
  (approximately 18 seconds).
- Student audio stopped 16:31:57 and the operator confirmed back rows returned
  to Settled at 16:32:12 (approximately 15 seconds).
- Submitted image shows lecturer speaking, back rows Talking, and front and
  middle rows Settled. Screenshot: `docs/evidence/node4-talking.png`.
- Gateway telemetry from 16:31:00 to 16:32:13 was saved in
  `2026-11-20-node4-speech-163100.csv`, with 146 windows per node. These
  times are operator observations, not instrumented latency measurements.
