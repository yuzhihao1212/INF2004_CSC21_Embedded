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
over `audio_smooth_s` (10 s). TALKING includes HOLD. QUIET/PENDING count as known negative
windows; UNKNOWN and calibration windows do not enter the denominator. At least
`reference_min_known_windows` (default 4) are required, and the TALKING fraction must
reach `reference_talking_fraction` (default 0.5). A brief unknown window does not erase
usable rolling evidence. When the rolling result is unknown, its evidence expires, or
either node is stale/offline, fusion falls back to the existing conversation probability
rule. It returns to reference comparison when usable known evidence returns. Calibration,
reset and JSON load clear old smoothing history. `/api/state` exposes `smoothed_state`,
`talking_fraction`, `known_windows` and `decision_source` beside the raw window `state`.

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

## Contributing

`main` is protected: all changes go through a pull request with passing CI and one approval.
Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for the step-by-step workflow.
