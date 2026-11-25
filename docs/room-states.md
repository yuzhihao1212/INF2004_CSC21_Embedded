# How MOSAIC decides what the room is doing

This page follows one reading from a sensor to the words on the dashboard. Every
threshold below is a default in `FusionConfig` (`pc/mosaic/fusion.py`) or the
gateway (`pc/mosaic/gateway.py`), and can be changed with `--fusion-config`
without touching code. The plain-language wording comes from `pc/mosaic/feedback.py`.

## 0. What the PC receives: one 64-byte report per node per second

All fusion works from one fixed-size packet per node, by default once a second:
a 16-byte header and a 48-byte body, integers only, little-endian. The full byte
layout is in [protocol.md](protocol.md#telemetry-node--pc-48-byte-payload-64-total);
this table shows what each field is for in fusion.

| Bytes | Field | Format | Used by fusion for |
|---|---|---|---|
| Header 4 | `node_id` | 1–8 | Which zone the report belongs to (node 1 = reference node at the lecturer's desk) |
| Header 5 | `flags` | bit 0 = first report since boot | After a node reboots, its pairing with the reference node and its speech persistence start again |
| Header 8–11 | `seq` | Counts up by 1 per message | Lost, repeated and out-of-order reports, and node status (Delayed, Not connected) |
| Header 12–15 | `sender_time_ms` | The node's own clock | Only to age a late or repeated report and to spot a reboot. The PC never compares two nodes' clocks |
| 12–13 | `temperature_x10` | 0.1 °C | Comfort, when the `TEMP_HUM` flag is set |
| 14–15 | `humidity_x10` | 0.1 % | Comfort, when the `TEMP_HUM` flag is set |
| 16–17 | `co2_ppm` | ppm | Air quality and "the room is still occupied", when the `CO2` flag is set |
| 18–19 | `config_version` | Applied CONFIG | Whether a setting change has really been applied |
| 20–21 | `audio_overruns` | Count | A change means windows were lost on the node: the lecturer-reference comparison for that zone restarts |
| 22–23 | `audio_window_seq` | Count | Windows missing between reports: the lecturer-reference comparison for that zone restarts |
| 24–39 | `audio[2]` | 2 windows × 8 bytes | All sound decisions (below) |
| 40 | `audio_window_count` | 0–2 | How many of the two windows are real |
| 41 | `pir_active_pct` | 0–100 | Motion, when the `PIR` flag is set |
| 42 | `valid_flags` | One bit per sensor | A reading is used only when its bit is set |

Each 8-byte audio window holds:

| Field | Format | Used by fusion for |
|---|---|---|
| `prob_pct[4]` | Background, speech, reserved (0), transient; percent | Summed over 10 s per zone: speech share, the lecturer's zone, uncalibrated talking |
| `rms_x16` | Loudness in ADC counts, Q12.4 | The lecturer-reference comparison, Excessive noise, the per-node noise floor, and "quieter than the lecturer, so it's the lecturer carrying" |
| `audio_class` | Label, or UNKNOWN when a gate failed | Shown on the Sensors page; fusion uses the probabilities instead |

The remaining fields (`dsp_time_us`, `inference_time_us`, `free_heap_bytes`,
`cpu_load_pct`, `wifi_rssi_dbm`) are node health for the Sensors page, not fusion
inputs. Free heap, CPU load and Wi-Fi signal are sent as 0: no node task fills them.

### Why the packet looks like this

- **Probabilities, not just labels.** A window that is 55% speech and one that is
  95% speech are different evidence. Fusion adds up the probabilities over 10 s,
  so borderline windows don't flip a zone back and forth.
- **Loudness travels with every window.** The classifier can't say *who* is
  speaking, since the lecturer's voice reaches every microphone. Comparing loudness
  between zones can, which is what the lecturer-reference comparison does.
- **Two windows per report.** A window is 500 ms and a report goes out every
  second, so every window reaches the PC. With one window per report, half of
  them would be thrown away.
- **Valid flags instead of zeros.** A CO₂ of 0 or a temperature of 0.0 °C could be
  a real value; a cleared flag can't be mistaken for one. Fusion turns a missing
  reading into *No reading*, never into an old or zero value.
- **Counters instead of clocks.** The Picos' clocks aren't synchronised, so the PC
  dates every window by when the report arrived: the newest window at the arrival
  time, the one before it 500 ms earlier. Counters (`seq`, `audio_window_seq`,
  `audio_overruns`) show what was lost or repeated.
- **Integers only, fixed size.** No floating point on the node, a fixed 64 bytes
  that is easy to check (wrong magic, version or length is dropped), and the
  same layout in C (`mosaic_protocol.h`) and Python (`protocol.py`), checked
  against each other by `pc/tests/test_protocol.py`.

### What the PC does with each report

1. **Check it.** The gateway drops anything with the wrong magic, version, type
   or length, works out lost and repeated reports from `seq`, and updates the
   node's status.
2. **Keep the usable parts.** Each audio window whose probabilities are valid
   is kept for that zone as *(arrival time, probabilities, loudness)*. Motion is
   kept only if `PIR` is set; CO₂, temperature and humidity replace the zone's
   last value only if their flag is set, and clear it if not.
3. **Pair with the reference node.** Student windows are matched with the
   reference node's window from the same moment, within 250 ms, for the
   lecturer-reference comparison.
4. **Decide, several times a second.** Over each zone's last 10 s of windows and
   60 s of motion, fusion adds up probabilities and loudness and compares them
   with the thresholds below. It uses whole-number sums and cross-multiplication
   (a share of at least 40% is checked as `sum × 100 ≥ 40 × count`), so there are
   no rounding surprises and no floating point here either.

## 1. On each Pico: what kind of sound is this?

Every 500 ms the node turns 8,000 microphone samples into 20 features and the
int8 network scores them as background, speech or transient noise.

A label is only sent when the evidence is good enough; otherwise the window is
UNKNOWN. The probabilities are sent either way.

| Gate | Rule |
|---|---|
| Too quiet | AC loudness below 4 ADC counts |
| Clipped | 80 or more of the 8,000 samples at the ADC's limit |
| Late | Result ready more than one 500 ms window after capture. This check cannot trip on the current build: see the clock limitation in `drv_audio.c` |
| Not confident | Winning class below the confidence threshold (60% by default, set from the dashboard) |
| Speech | Needs two windows in a row with speech probability of at least 50% |

Each report carries the last two windows (class, probabilities and loudness),
plus PIR motion, temperature, humidity and CO₂, each with a "valid" flag.

## 2. On the PC: is the data usable?

| Check | Rule |
|---|---|
| Node status | **Delayed** after 3 missed reports; **Not connected** after 10 s with no report |
| Invalid values | A reading whose valid flag is off is dropped, never shown as an old value |
| Bad audio windows | Probabilities out of range or using the reserved slot are dropped |
| Noise floor | A window quieter than that node's configured floor counts as background |

Each zone keeps its last 10 seconds of audio windows and its last 60 seconds of
motion readings.

## 3. Each zone's state

The first rule that matches wins.

| Order | Shown as | Rule |
|---|---|---|
| 1 | **No signal** / **Not connected** | Node offline, or no valid audio window recently |
| 2 | **Excessive noise** | Student zones with a noise limit set in Setup only. At least 70% of the last 10 s of windows reach the limit, whatever the sound is. It clears below 50% |
| 3 | **Lecturer's voice** | The reference zone only: at least 50% speech over 10 s, and speech is its strongest class |
| 4 | **Talking** | Student zones only. See below |
| 5 | **Moving around** | PIR saw motion in at least 10% of the last 60 s |
| 6 | **Settled** | None of the above |

**How "Talking" is told apart from the lecturer's voice carrying.** The lecturer's
voice reaches every microphone, so speech at a student desk alone proves nothing.

- **After voice set-up (calibration):** while only the lecturer speaks, the PC
  pairs each student window with the reference node's window from the same
  moment (within 250 ms) and learns, from at least 20 pairs, how loud the lecturer
  sounds at that desk. Afterwards a window counts as local talking only when it
  is louder than that prediction by 25% plus 4 ADC counts and its speech
  probability is at least 60%. The zone shows Talking when at least half of its
  recent paired windows do (at least 4 of them).
- **Before calibration:** the zone needs speech in at least 40% of its windows
  (25% to stop), and while the lecturer is speaking it must also be at least 75%
  as loud as the lecturer's zone. Anything quieter is taken to be the lecturer's
  voice carrying. In Quiet work the thresholds are 25% to start and 15% to stop.

A zone's state has to hold for **10 seconds** before the map changes, so one
cough doesn't flip it. *No signal* is the exception and shows at once.

## 4. The room's state (the headline)

**Is anyone there?** Motion of 10% or more, or speech in 40% or more of the
windows, in any zone counts as evidence. It takes 20 s of evidence to leave
*Room is empty*, and 10 minutes with none to return to it. Raised CO₂ (800 ppm or
more) keeps an occupied room occupied, but can't declare it occupied, because
CO₂ lags.

**If the room is occupied:**

| Class type | Rule | Shown as |
|---|---|---|
| Lecture or Quiet work | Any student zone talking | **Getting noisy**, then **Ongoing chatter** after 2 minutes |
| Group work | At least half the student zones talking | **Group discussion** |
| Any | No student zone talking, lecturer's zone speaking | **Lecture in progress** |
| Any | None of the above | **Quiet** |

The room's state has to hold for **20 seconds** before the headline changes.

## 5. Air and comfort

| Card | Rule | Hold time |
|---|---|---|
| Air, per zone | Below 800 ppm **Fresh**, below 1,200 **Getting stuffy**, otherwise **Stuffy** | 10 s |
| Air, room | Uses the stuffiest zone: **Stuffy** at 1,200 ppm or more, **Fresh** again only below 1,000 | 60 s |
| Comfort, room | Average of every zone: **Uncomfortable** outside 20–28 °C or 30–70 % humidity, with a 0.5 °C and 3 % margin before it clears | 60 s |

No valid reading shows *No reading* or *Sensor warming up* (the CO₂ sensor takes
two minutes after power-on), never a stale number.

## 6. How urgent it is

The same state can be fine in one class and a problem in another, so the colour
and any alert depend on the class type.

| Situation | Lecture | Quiet work | Group work |
|---|---|---|---|
| Getting noisy | Heads up | Heads up | Not raised: talking in fewer than half the zones counts as Quiet |
| Ongoing chatter | **Act now**, with an alert | **Act now**, with an alert | Fine |
| Excessive noise | **Act now**, with an alert | **Act now**, with an alert | Heads up |
| Lecture in progress | Fine | Heads up | Fine |
| Stuffy air (room occupied) | **Act now**, with an alert | **Act now**, with an alert | **Act now**, with an alert |
| Uncomfortable | Heads up | Heads up | Heads up |
| Fewer than half the sensors working | **Act now**, with an alert | **Act now**, with an alert | **Act now**, with an alert |

An alert ends by itself when the situation clears; **Hide** keeps it off the
banner for 10 minutes. Every state change and alert is written to the event log
with its reason (for example "conversation in C"), and shown in History.

## Where to check this

- Rules: `pc/mosaic/fusion.py` (`_zone_candidate`, `_occupied_candidate`,
  `_step_air`, `_step_comfort`) and `pc/mosaic/reference.py`.
- Wording and urgency: `pc/mosaic/feedback.py`.
- Tests: `pc/tests/test_fusion.py`, `test_reference.py` and `test_scenarios.py`,
  which plays every scripted scenario and fails if a phase no longer reaches its
  state.
