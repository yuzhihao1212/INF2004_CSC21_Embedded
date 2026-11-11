# INF2004_CSC21_Embedded

MOSAIC: Multimodal Observation and Sensor-fusion Architecture for Intelligent Classrooms.
See [docs/](docs/) for the project brief and team workflow.

## Repository layout

```
firmware/          Pico W firmware (CMake project "mosaic")
  CMakeLists.txt   SDK import and project setup
  tests/           Standalone sensor / DSP bring-up targets, one .uf2 each
ml/                Audio dataset preparation, feature extraction and model training
  scripts/         Run from the repository root, e.g. python ml/scripts/train_pico_model.py
  data/            Feature datasets (raw audio folders are git-ignored)
pc/                PC-side gateway, sensor fusion and dashboard
  mosaic/          Protocol v2, gateway receiver and node simulator
  tests/           Unit tests, run from pc/ with python -m unittest
  prototype/       Early text-format UDP sender/receiver (superseded by mosaic/)
docs/              Project brief and team workflow
```

## Building the firmware

The team uses Raspberry Pi Pico SDK v1.5.1 with `PICO_BOARD=pico_w`.

- **VS Code:** open the repository root. `.vscode/settings.json` already points CMake at
  `firmware/` and builds into `firmware/build/`.
- **Command line:**

  ```
  cmake -S firmware -B firmware/build -G Ninja -DPICO_SDK_PATH=<path to pico-sdk>
  ninja -C firmware/build
  ```

Each target in `firmware/tests/` produces its own `.uf2` in `firmware/build/tests/`.
Never commit `build/` folders; they are git-ignored.

## Python environment

```
python -m venv .venv
pip install -r requirements.txt
```

## Running the PC gateway

From the `pc/` folder (the gateway itself needs only the Python standard library):

```
python -m mosaic.gateway --csv telemetry.csv
```

It listens on UDP 5005, prints each node's readings, and every 10 s prints a table with
each node's status (ONLINE/STALE/OFFLINE), packet loss, reboots and PING round-trip time.
To test without hardware, run the simulated nodes in a second terminal:

```
python -m mosaic.simulator --nodes 3 --loss 0.1 --reboot-every 30
```

On Windows, allow Python through the firewall when asked so real nodes can reach port 5005.

### Live dashboard

```
python -m mosaic.dashboard                 # then open http://localhost:8050
python -m mosaic.dashboard --simulate 3    # rehearse with simulated nodes, no second terminal
```

The dashboard runs the gateway and serves a web page with each node's status, readings,
audio class and link quality, plus CO₂ and temperature trends for the last 1–10 minutes.
A pill in the top bar says whether the data is **Simulated** (sent from this computer),
from real **Sensors**, or **Mixed**; simulated node cards are also tagged.
Add `--http-host 0.0.0.0` to open it from another device on the same network, `--csv FILE`
to log readings, and `--verbose` to also print every packet.

To change a node's settings, POST only the fields you want to change. The gateway then delivers
them as a CONFIG, retrying until the node acknowledges, and resends after the node reboots:

```
curl -d '{"report_interval_ms": 500, "mode": "DISCUSSION"}' http://localhost:8050/api/nodes/1/config
```

Fields and ranges are listed under CONFIG in [docs/protocol.md](docs/protocol.md). The
`config` entry for each node in `/api/state` shows the delivery's progress. There are no
buttons on the page for this yet.

### Classroom states (fusion)

The gateway and dashboard run the fusion engine (`pc/mosaic/fusion.py`, statechart 6.4). It
combines every zone's audio probabilities, PIR motion, CO₂ and temperature/humidity into
three parallel states: **activity** (empty, quiet, focused lecture, discussion, noise rising,
sustained chatter), **air** (normal or poor ventilation) and **comfort**. The page shows them
under *Classroom*, with buttons that switch the classroom mode (Lecture, Discussion, Quiet work)
for fusion and every node at once.

Thresholds, dwell times and the node → zone map are defaults in `FusionConfig`. To tune them
without editing code, pass a JSON file containing only the values to change:

```
python -m mosaic.dashboard --fusion-config fusion.json
```

where `fusion.json` is, for example, `{"co2_poor_ppm": 1500, "zones": {"1": "A", "2": "C"}}`.
`pc/tests/test_fusion.py` holds the scripted scenarios (lecture, chatter, discussion,
ventilation and so on) that check the rules.

To demonstrate the states without hardware, run a scripted classroom:

```
python -m mosaic.dashboard --scenario demo
```

Four simulated nodes play the scenario. The console announces each phase and the state it
should produce, and prints every classroom state change. Scenarios (defined in
`pc/mosaic/scenarios.py`):

| Scenario | Shows | Length |
|----------|-------|--------|
| `lecture` | empty → lecture → rear chatter (noise rising → sustained chatter) → settles | 8 min |
| `discussion` | group work: noise in Lecture mode, **Discussion** if you click that mode | 6 min |
| `ventilation` | CO₂ builds up → poor ventilation → window opened → normal | 6 min |
| `comfort` | air-conditioning fails → out of range → restored | 6 min |
| `exam` | silent, motionless exam stays occupied (PIR is motion, not presence) | 6 min |
| `demo` | all of the above in one run | 18 min |
| `reference` | lecturer-only calibration → attenuated lecture → local speech at node 3 → lecture | 7 min |

`pc/tests/test_scenarios.py` plays each one through the fusion engine and fails if a phase no
longer reaches its state, for example after a threshold is changed.

## Running a real node

`firmware/node/` builds `mosaic_node.uf2`: DHT22, CO₂ and PIR readings sent as protocol v2
TELEMETRY every second over Wi-Fi (audio not wired in yet).

1. Copy `firmware/node/node_config.example.cmake` to `firmware/node/node_config.cmake` and set
   the node ID, Wi-Fi name and password, and the PC's IP address (`ipconfig` on Windows,
   `ipconfig getifaddr en0` on macOS). This file is git-ignored; never commit it.
2. Reconfigure and build (VS Code: **CMake: Delete Cache and Reconfigure**, then build), and
   flash `firmware/build/node/mosaic_node.uf2`.
3. Start `python -m mosaic.dashboard` (or `python -m mosaic.gateway`) on the PC. The Pico
   and PC must be on the same network, and the network must allow devices to talk to each
   other (many campus and guest Wi-Fi networks don't; a phone hotspot works).
4. Check the PC can reconfigure the node: run the dashboard with `--verbose`, then send
   `curl -d '{"report_interval_ms": 500}' http://localhost:8050/api/nodes/1/config`
   (use your node ID). The console prints `CONFIG 1 applied` once the node acknowledges.
   The node only accepts CONFIG from the PC IP it was built with.

The onboard LED blinks once per packet sent. Wi-Fi status and the node's IP are printed on
the USB serial port. The node uses the SDK's interrupt-driven background Wi-Fi servicing
(still no FreeRTOS). Receive callbacks validate and copy CONFIG/PING into a four-entry
queue; the main loop applies configuration and sends replies. Foreground lwIP calls are
locked. A full control queue drops the new packet without blocking, so CONFIG retries can
recover. Serial health messages report telemetry send attempts and control-queue drops
every 10 s; a successful send means lwIP accepted it, not that the PC received it.

After flashing, leave the dashboard and USB serial monitor open for a 10-minute run, then
repeat the CONFIG check above while the node is ONLINE. Confirm both the node's
`CONFIG ... applied` message and the gateway's acknowledgement; an HTTP
`config_version` response alone only confirms that the PC queued the update. Record any
CYW43 timeouts or OFFLINE periods. A join or DHCP attempt stuck for 30 s restarts station
mode, and RSSI is queried only while connected, at most once every 5 s.

For unreliable Wi-Fi, each telemetry report has up to two short, bounded retry
copies. The updated gateway deduplicates them and repairs tracked gaps without
counting late copies as reboots or rewinding live readings. Flash and run the
updated node and PC code together. The gateway summary/API exposes recovered
messages, first-observed gaps and duplicates separately. Dashboard loss means
**unrecovered unique messages**, not raw radio loss; raw packet-loss evidence
and the N10 result must still be retained separately. There is no delivery
guarantee during an outage: retry storage is fixed and expires after 600 ms.
### Zone map and integer fusion

The Classroom panel includes a floor-plan heatmap with Activity, CO₂, Temperature
and Motion views. Buttons work with Tab and Enter/Space; icons and labels accompany
colour. The front/lecturer's desk and reference zone are marked; stale cells dim,
offline cells hatch. Each zone has its own 10-second dwell (configuration
`zone_dwell_ms`), faster than the classroom activity dwell. Configure positions
with `zone_layout`, for example `{"A":[0,0],"B":[0,1],"C":[1,0],"D":[1,1]}`;
row 0 is at the front. Every configured zone must have a unique cell.

Fusion decisions now use integer milliseconds, exact sums/counts, scaled wire
values and Q16 reference gain. Configuration names use explicit units; old
seconds/fraction/°C keys were renamed without a compatibility shim. See
[the numeric representation and comparison evidence](docs/fusion_numeric_representation.md)
for all ranges, rounding, renames and the AST enforcement allow-list. Saved
reference baselines use integer JSON version 2: recalibrate old version 1 files.
Dashboard decimal values are presentation only.

### Lecturer-reference comparison

Place reference node **1 / zone A** at the lecturer's desk. In *Classroom*, click
**Calibrate** while only the lecturer speaks and student areas stay quiet. Vary the
lecturer's level naturally: each student zone needs at least **20 usable paired
500 ms windows** and enough level variation to fit its baseline. Recalibrate after
moving microphones, changing gain or rebooting nodes. **Reset** discards the baseline
without starting collection. The row shows each zone's progress/state; hover for RMS,
expected lecturer level, threshold and gain. `/api/state` exposes the same values under
`classroom.reference.zones` and each classroom zone's `reference` entry.

The PC fits `student_power = gain * reference_power + background_power` and compares
student RMS with `sqrt(expected_power + upper_residual) * 1.25 + 4`. The residual is
the nearest-rank 95th percentile of nonnegative calibration errors. Speech evidence
is `100 - background_probability - transient_probability`, independent of the reported
lecturer/student class. Above-threshold speech needs two consecutive windows; one weak
window is held, the second releases. As in Darius's C policy, RMS below 4 resets
immediately. Missing, invalid or replayed audio and stale/offline nodes clear window
persistence to **UNKNOWN**. Gaps reset onset/hold but the windows that did arrive are
still processed; a 2-second report interval must not discard every report.

For activity rules, fusion smooths each calibrated zone's actual paired-window results
over `audio_smooth_ms` (10000 ms). PENDING and TALKING (including HOLD) both count as positive
evidence: the 10-second smoother replaces the per-window onset gate. QUIET counts
as a known negative window; UNKNOWN and calibration windows do not enter the denominator. At least
`reference_min_known_windows` (default 4) are required, and the TALKING fraction must
reach `reference_talking_pct` (default 50). A brief unknown window does not erase
usable rolling evidence. When the rolling result is unknown, its evidence expires, or
either node is stale/offline, fusion falls back to the existing conversation probability
rule. It returns to reference comparison when usable known evidence returns.
Fusion uses the applied CONFIG report intervals supplied by the gateway: rolling
freshness is at least one report interval plus 500 ms batching age and pairing
tolerance (2750 ms for 2-second reports at default tolerance). Strict per-window
pairing/expiry stays unchanged. This allows asymmetric 2-second streams to use
PENDING evidence without restarting classroom dwell between reports. Very sparse
reports still need four known windows within the 10-second smoothing period;
otherwise fusion falls back to probabilities. Direct Python integrations must
pass the applied `report_interval_ms` keyword to `FusionEngine.add` (default 1000). Calibration,
reset and JSON load clear old smoothing history. `/api/state` exposes `smoothed_state`,
`talking_pct`, `known_windows` and `decision_source` beside the raw window `state`.

All comparison runs on the PC, with no node-to-node relay or shared Pico clock. Window
times are estimated from PC receive time, spacing the oldest-first windows by 0.5 s;
pairs must be within 0.25 s. Small RTT alone is not enough: independent audio/report
clocks can leave a window waiting about 0.5 s before transmission. Receive-time estimates
therefore still misalign some pairs; smoothing stabilises the classroom decision without
relaxing the per-window gates. Protocol v2 has no per-window clipping/quality flags, so the
PC cannot reproduce the C service's clipping checks; empty/malformed audio, sequence
gaps and changes to `audio_overruns` are used where observable. Invalid/overrun reports
are discarded; skipped windows reset persistence while keeping the frozen baseline.

Try from `pc/`:

```
python3 -m mosaic.dashboard --scenario reference
python3 -m mosaic.dashboard --scenario reference --receive-jitter-ms 80
```

Click **Calibrate** during the first 60-second phase. Speech probabilities remain high
in every zone during both lecture-only and student-speech phases; only node 3's higher
RMS distinguishes them. Console announcements explain each phase. Tests start calibration
explicitly and play all phases without sleeping; the application never auto-calibrates.
Simulated nodes now have independent seeded audio/report phases and small audio-clock
drift. RMS follows the true window completion time, before batching and optional receive
jitter. Reports carry only the newest completed windows (0-2); skipped windows remain
visible in `audio_window_seq`. Use `--aligned` for the old aligned fixture, or run the
standalone simulator with `--seed N` for reproducibility. The timing regression includes
reference phases 0.00/0.40 s, student phases 0.35/0.65 s and 0-80 ms receive jitter:

```
python3 -m unittest tests.test_reference_timing -v
```

`FusionConfig.reference_zone` defaults to `"A"`; JSON `{"reference_zone": null}` disables
comparison. The `reference_*` settings in `pc/mosaic/fusion.py` configure pairing, age/gap
limits, speech gates, margins and pair counts (20-64). An unmapped reference zone also
disables comparison. Calibration requests accept `{}` for all student zones, or
`{"zone": "C"}` for one:

```
curl -d '{}' http://localhost:8050/api/calibrate
curl -d '{"zone":"C"}' http://localhost:8050/api/calibrate/reset
```

Python integrations can call `engine.reference.save("baseline.json")` and
`engine.reference.load("baseline.json")`. Only frozen baselines are saved; load requires
the same zone map/settings and waits for fresh pairs, never restoring a TALKING alert.
These prototype margins are not validated classroom accuracy or speaker identification.

## Evaluating a test run

From `pc/`, record both telemetry and events, then stop with Ctrl+C:

```sh
python3 -m mosaic.dashboard --scenario lecture --csv /tmp/run.csv --events /tmp/run.jsonl
# Hardware-only receiver: python3 -m mosaic.gateway --csv /tmp/run.csv --events /tmp/run.jsonl
python3 -m mosaic.evaluate /tmp/run.csv --events /tmp/run.jsonl --out /tmp/report.md --json /tmp/summary.json --deadline-ms 400
python3 -m mosaic.evaluate /tmp/run.csv --events /tmp/run.jsonl --expected ../docs/lecture_expected.csv --out /tmp/scored.md --json /tmp/scored.json
```

The lecture scenario lasts 450 s; shorter runs score only labels inside the
capture. The example timeline labels stable scripted phases; replace it with
human annotations for real accuracy measurements. Reports include delivery,
receive jitter, processing percentiles, deadline bounds, audio skips/overruns,
RTT, availability/recovery, warm-up, and classroom/zone state durations and
transitions. Percentiles use `statistics.quantiles` with the inclusive method.
Record events for accurate loss: telemetry CSV alone omits PONG/ACK sequence
numbers. Exact positive per-window deadline misses cannot be inferred from the
protocol's separate DSP/inference maxima. See [metric definitions and event
schema](docs/evaluation.md) for units, scoring and limits. Existing CSVs remain
readable; use separate file names for each labelled experiment.

## Contributing

`main` is protected: all changes go through a pull request with passing CI and one approval.
Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for the step-by-step workflow.
