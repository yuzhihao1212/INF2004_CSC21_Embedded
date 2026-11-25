# PC gateway and dashboard

The deployed MOSAIC node uses MQTT. The gateway, fusion and dashboard use
Python's standard library. See the [main README](../README.md) for board and
broker configuration.

From this directory:

~~~sh
python -m mosaic.dashboard --mqtt localhost --csv telemetry.csv --events events.jsonl
# Gateway only:
python -m mosaic.gateway --mqtt localhost --csv telemetry.csv --events events.jsonl
# Simulated local run without boards or broker:
python -m mosaic.dashboard --simulate 4
~~~

Open http://localhost:8050. The dashboard runs its own gateway; stop it before
starting a separate gateway on the same transport. Use distinct CSV and JSONL
paths for each experiment. Install the optional ML/data dependencies from
[requirements.txt](../requirements.txt) when needed. The earlier UDP firmware
uses these same commands with the MQTT option omitted.

Run the PC unit tests with `python -m unittest -v` from this directory.

### Live dashboard

```
python -m mosaic.dashboard --mqtt localhost   # real nodes
python -m mosaic.dashboard --simulate 4    # rehearse with simulated nodes, no second terminal
```

The dashboard runs the gateway and serves a plain-language web page with four pages
(design and accessibility rationale: [docs/ui_design.md](../docs/ui_design.md)):

| Page | For | Shows |
|---|---|---|
| **Live room** | The lecturer, at a glance | One headline ("Lecture in progress") and summary, the class type, and a live floor plan of the room where each area shows what it's doing (sound rings for voices and noise, a haze for stuffy air). Beside it: the alert with one suggested action, loudness against the noise limit, air, comfort and the latest changes. Below: the last 10 minutes as one coloured bar. Select an area for all its readings. The map has a **Flat / 3D** switch (3D is an isometric diorama of the room). Press **P** for presenter mode |
| **History** | What happened | A timeline of changes and cleared alerts, and CO₂/temperature charts with a text summary |
| **Sensors** | The team | Each sensor's readings, sound class, Wi-Fi signal, lost readings and response time |
| **Setup** | Changing things | Class type, voice setup (lecturer calibration), noise limit (excessive noise), how often sensors report, technical names, theme |

When something needs action (ongoing chatter or excessive noise in a lecture, stuffy air in an
occupied room, or fewer than half the sensors working), a card with one suggested action appears beside
the map on the Live room, and as a banner on top of every other page. It clears by itself when the situation ends; **Hide** removes it for 10 minutes but keeps
it in History. Alerts are also written to `--events`. **Setup › Show technical names** adds the
engine's state names (`FOCUSED_LECTURE`, …) and raw numbers, for testing and assessment.
A pill in the top bar says whether the data is **Simulated** (sent from this computer) or
**Partly simulated**. The page loads nothing from the internet (its font, Plus Jakarta Sans
under the SIL OFL, ships in `pc/mosaic/web/`), so it works on a hotspot. Add `--http-host 0.0.0.0` to open it from another device on the same
network, `--csv FILE` to log readings, and `--verbose` to also print every packet.

To change a node's settings, POST only the fields you want to change. The gateway then delivers
them as a CONFIG, retrying with a bounded send count and tracking the acknowledgement. It resends after a node reboot:

```
curl -d '{"report_interval_ms": 500, "mode": "DISCUSSION"}' http://localhost:8050/api/nodes/1/config
```

Fields and ranges are listed under CONFIG in [docs/protocol.md](../docs/protocol.md). The
`config` entry for each node in `/api/state` shows the delivery's progress. The Setup page
uses this for the class type and report interval.

### Classroom states (fusion)

The gateway and dashboard run the fusion engine (`pc/mosaic/fusion.py`, statechart 6.4). It
combines every zone's audio probabilities, PIR motion, CO₂ and temperature/humidity into
three parallel states: **activity** (empty, quiet, focused lecture, discussion, noise rising,
sustained chatter), **air** (normal or poor ventilation) and **comfort**. The page shows them
in plain words (`pc/mosaic/feedback.py`), with a class-type control (Lecture, Group work, Quiet
work) that switches fusion and every node at once.

Nodes report background, speech and transient noise. Protocol v2 keeps four probability
slots, with slot 3 reserved and zero. Fusion assigns the lecturer role to
`reference_zone` (default A). A focused lecture needs dominant speech there and no
detected student talk. The other zones use calibrated reference comparison when its
result is known, or their smoothed speech probability otherwise. Discussion mode
requires talk in a configurable share of student zones with audio; Lecture and Quiet
Work can raise an alert from one student zone. If the reference zone is null or unmapped,
all zones use the student speech rule and `FOCUSED_LECTURE` is unavailable: without a
lecturer location the model cannot tell a lecture from a student speaking.

Thresholds, dwell times and the node → zone map are defaults in `FusionConfig`. To tune them
without editing code, pass a JSON file containing only the values to change:

```
python -m mosaic.dashboard --fusion-config fusion.json
```

where `fusion.json` is, for example, `{"co2_poor_ppm": 1500, "zones": {"1": "A", "2": "C"}}`.
Use `lecturer_zone_speech_pct` for the lecturer's speech gate. The old JSON key
`lecture_speech_pct` still loads with a deprecation warning; the new key takes priority
if both are present. The `conversation_*` and `quiet_work_conversation_*` thresholds
now apply to the student zones' speech fallback. `front_zones` is accepted in older
configs; it no longer assigns the lecturer role.
`pc/tests/test_fusion.py` holds the scripted scenarios (lecture, chatter, discussion,
ventilation and so on) that check the rules.

**Excessive noise.** Each student area can have a noise limit. Under it, a noisy area
shows *Talking*; at or above it for long enough, it shows *Excessive noise* (zone state
`LOUD`). To set a limit, play a steady sound next to the area's sensor at a target level
read on a phone sound-meter app, and capture it: **Setup › Noise limit** walks through each
area with a live meter, or POST `{"zone": "C"}` to `/api/loudness/capture` (and
`/api/loudness/clear` to remove it). The limit is the sensor's mean `rms_x16` over
`loud_capture_ms` (5 s). An area is `LOUD` while at least `loud_enter_pct` (70%) of its
audio windows in `audio_smooth_ms` (10 s) reach the limit, `loud_exit_pct` (50%) to leave,
after the usual `zone_dwell_ms`. Any sound class counts; the lecturer's area is never
checked, since the lecturer speaks right next to it. Without a limit an area keeps today's
rules. Pass `--loud-levels FILE` to keep the limits across restarts, or put them in the
fusion config as `loud_levels_x16`. It's *Act now* with a banner in Lecture and Quiet
work and a heads-up in Group work. The node reports unweighted AC RMS in ADC counts, not
dB(A): describe a limit as "about 70 dB at the sensor". The 70 dB target on the Setup page
is a placeholder until we cite a classroom noise limit (to verify).

To demonstrate the states without hardware, run a scripted classroom:

```
python -m mosaic.dashboard --scenario demo
```

Four simulated nodes play the scenario. The console announces each phase and the state it
should produce, and prints every classroom state change. With a scenario and no saved limits,
each student area gets a stand-in noise limit (`SIM_LOUD_RMS`, 150 ADC RMS) so the rowdy
phase shows *Excessive noise* without a sound meter. Scenarios (defined in
`pc/mosaic/scenarios.py`):

| Scenario | Shows | Length |
|----------|-------|--------|
| `lecture` | empty → lecture → rear chatter (noise rising → sustained chatter) → settles | 8 min |
| `discussion` | group work: noise in Lecture mode, **Discussion** if you click that mode | 6 min |
| `ventilation` | CO₂ builds up → poor ventilation → window opened → normal | 6 min |
| `comfort` | air-conditioning fails → out of range → restored | 6 min |
| `exam` | silent, motionless exam stays occupied (PIR is motion, not presence) | 6 min |
| `demo` | all of the above in one run, plus the back rows getting rowdy (**Excessive noise**) | 20 min |
| `reference` | lecturer-only calibration → attenuated lecture → local speech at node 3 → lecture | 7 min |

`pc/tests/test_scenarios.py` plays each one through the fusion engine and fails if a phase no
longer reaches its state, for example after a threshold is changed.

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
[the numeric representation and comparison evidence](../docs/fusion_numeric_representation.md)
for all ranges, rounding, renames and the AST enforcement allow-list. Saved
reference baselines use integer JSON version 2: recalibrate old version 1 files.
Dashboard decimal values are presentation only.

### Lecturer-reference comparison

Place reference node **1 / zone A** at the lecturer's desk. In Setup › Voice setup, click
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
# Hardware-only receiver: python3 -m mosaic.gateway --mqtt localhost --csv /tmp/run.csv --events /tmp/run.jsonl
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
schema](../docs/evaluation.md) for units, scoring and limits. Existing CSVs remain
readable; use separate file names for each labelled experiment.
