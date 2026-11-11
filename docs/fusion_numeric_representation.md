# PC fusion numeric representation (CSC21)

Scope: `pc/mosaic/fusion.py` and `pc/mosaic/reference.py`. This is evidence for PC
sensor-fusion mathematics; it does not establish compliance of firmware DSP,
TinyML, sensor conversions or node-health calculations. The assigned requirement
remains verbatim in `docs/change_requirement_csc21.md`.

## Boundaries and rounding

The caller supplies Python monotonic **seconds** to `add`, `evaluate`, `calibrate`
and `set_mode`. Each public call converts once through **`reference.seconds_to_ms`**,
rounding to the nearest millisecond, ties away from zero. This is the only function
allowed to use floating-point operations. The engine forwards the integer timestamp
to reference's `add_ms` / `evaluate_ms` / `calibrate_ms`; there is no second conversion.
Explicit `*_ms` entry points require actual Python integers (not bool or float).
Clock resolution loses at most 0.5 ms per timestamp; interval errors are at most 1 ms.
The clock is PC receive time, not a synchronised Pico clock.

All subsequent arithmetic, history timestamps, coefficients, counters, thresholds
and comparisons are integers. `round_ratio(n, d)` implements rational rounding to
nearest, ties **away from zero**, using integer operations and a positive divisor.
Q16 predictions truncate toward zero (all operands are nonnegative). Averages keep
sums and counts: for percent inputs, `sum >= threshold_pct * count`; for fractions,
`positive_count * 100 >= required_pct * count`. **Rounded display means are never
used for a decision.**

Python integers have arbitrary precision: sums, covariance, squared powers and cross
products do not wrap or overflow. No artificial upper saturation is applied to these
intermediates. Null (`None`) represents unavailable data, never a numeric sentinel.
Enums and booleans represent discrete state, validity and persistence flags.

## Inputs, histories and outputs

| Name(s) | Unit / valid range | Representation / scaling | Rounding, saturation and overflow |
|---|---|---|---|
| Public `now` | Finite monotonic seconds; negative virtual test epochs allowed | Clock boundary only | Nearest ms, half away; nonfinite/bool/nonnumber rejected |
| `now_ms`, `_now_ms`, `Event.time_ms`, `_Region.since_ms`, `_candidate_since_ms`, `_Window.time_ms`, `started_ms`, paired/history/stream timestamps | Integer ms, no fixed-width limit | int, 1 ms | Exact after boundary; `None` for no start/pair; no overflow |
| Per-node `report_interval_ms` | 200..10000 ms | int; applied CONFIG metadata, default 1000 | Invalid direct API values rejected; no inferred/shared clock |
| Rolling `freshness_ms` | >=reference_max_age_ms, no fixed-width limit | int ms; formula below | Exact max/addition; bounded also by smoothing window and gateway liveness |
| `WINDOW_MS`, `Q16`, `MAX_RMS_X16`, `EVENT_HISTORY` | 500 ms, 65536, 65535, 50 entries | Integer constants | Exact; event history truncates to 50 entries; comparison tests drain all events |
| `audio_window_seq`, previous sequence, `delta` | 0..65535 windows | uint16 represented as int; difference modulo 65536 | Invalid noninteger/out-of-range rejected; delta >=32768 is replay/backwards |
| `audio_overruns` | 0..65535 windows | uint16 represented as int | Invalid rejected; changed count resets persistence and discards report |
| Audio window count, `new_count` | 0..2 windows/report | int | Protocol cap; skipped windows reset persistence but newest received windows continue |
| `rms_x16`, `_Window.rms_x16`, `student_rms_x16` | 0..65535 (0..4095.9375 ADC RMS) | Q12.4, multiply ADC RMS by 16 | Raw wire integer; invalid audio rejected, not silently clipped |
| `prob_pct`, `_Window.speech_pct` | 0..100 percent | int, 1% | Each slot must be integer 0..100; slot 3 must be zero; sum must be 1..100 for fusion. Level comparison uses speech evidence = 100 - background - transient; probability fallback uses slot 2 directly |
| `temperature_x10` | -32768..32767 (-3276.8..3276.7 °C wire range) | Signed int, tenths °C | Direct callers clamped to wire range; validity bit required |
| `humidity_x10` | 0..1000 (0..100% RH physical range) | int, tenths %RH | Direct callers clamped to physical range within uint16; validity bit required |
| `co2_ppm` | 0..65535 ppm | int, 1 ppm | Direct callers clamped to uint16; warmup/invalid yields null |
| `pir_active_pct` | 0..100 percent | int, 1% | Direct callers clamped to percent range; validity bit required |
| `ZoneView.prob_sums`, `audio_count` | Class sums 0..100*N; N >=0 | Exact integer sums/count | Windows retained through inclusive history cutoff; no divide in rules |
| `ZoneView.motion_sum`, `motion_count` | 0..100*N; N >=0 | Exact integer sums/count | No divide in rules; missing samples do not become zero samples |
| Classroom temperature/humidity sums, sample count | Sum of valid scaled readings; count 0..8 | int x10 sums | Compare sum to bound * count; no rounded average in rules |
| Known reference count, TALKING count | 0..N windows in smoothing period | int | QUIET negative; PENDING/TALKING/HOLD positive; UNKNOWN/calibration excluded; each paired result consumed once |
| `talking_pct`, `probs_pct`, `motion_pct` outputs | 0..100 percent or null | Rounded integer percentages | Half away from zero, presentation metrics only |
| `confidence_pct` | 0..100 percent | int; ONLINE weight 100, STALE weight 50, missing weight 0 | Exact weighted sum / configured count, rounded half away; decision rules do not use confidence |
| Calibration `powers`: x, y | 0..4294836225 ADC²*256 | int = rms_x16² (Q24.8 power) | Exact square; no overflow |
| Least-squares `sx`, `sy`, `sxx`, `sxy`, covariance numerator and denominator | Nonnegative sums; covariance can be signed before clamp | Exact arbitrary-precision int | No intermediate rounding or overflow; <=64 pairs |
| `gain_q16` | >=0, no fixed upper limit; 65536 = gain 1 | Nonnegative Q16 | Exact rational coefficient rounded half away, then saturate >=0; arbitrary-precision storage |
| `background_power_x256` | >=0; fitted intercept <= max observed local power | int ADC²*256 | Exact rational intercept rounded half away; negative intercept triggers zero-intercept refit |
| Prediction `expected_power_x256` | >=0, no artificial upper limit | `(gain_q16 * ref_power >> 16) + background_power_x256` | Product truncated by right shift; no overflow |
| Positive errors, `upper_residual_x256` | >=0, fitted errors <= max observed local power | int ADC²*256 | Errors clamp at zero; sorted nearest-rank index `(95*N + 99)//100 - 1` |
| `threshold_power_x256` | >=0, no artificial upper limit | expected_power_x256 + upper_residual_x256 | Exact sum; pre-margin power, **not** an RMS threshold |
| Adjusted local RMS | -65535..65535 with configured margin | int x16 | Reject candidate unless positive before squaring; no square-root approximation in decisions |
| `positive`, `weak`, `hold` | 0..2, 0..1, bool | Integer onset/hold counters | Saturating onset count 2; one weak window held, second releases; low level resets immediately |
| `saved_pairs`, `pairs_collected` | 0..64 windows; calibrated model >= configured minimum | int | Collection capped at max_pairs; no overflow |
| Reference revision counter | >=0 | int | Incremented on reset/calibrate/load; clears rolling history |
| Node ID, zone label | IDs 1..8, unique nonempty string labels | int / string | Duplicate labels rejected; unmapped node ignored |
| `zone_layout`, per-zone `layout` | Each cell [row,col], each component 0..7 | int coordinates, zero-based; row 0 at front | Exactly all configured zones; unique cells; bool/fraction rejected |
| Mode, classroom/zone activity, air, comfort, reference state, status | Finite enumerations | Enum / JSON string | No arithmetic; offline map cells retained with NO_DATA and UNKNOWN environment |

## Configuration: every numeric field

All numeric JSON configuration values must be integers, not decimal numbers or booleans.
There are no team configuration files to migrate; old names are rejected as unknown keys.
Defaults below preserve the original thresholds and time intervals.

| Field(s) | Default | Unit / valid range | Representation / rounding / saturation |
|---|---|---|---|
| `reference_pair_tolerance_ms` | 250 | ms, >=0 | int, exact, invalid rejected |
| `reference_max_age_ms` | 1500 | ms, >=500 | int; strict per-window age and minimum rolling freshness |
| `reference_max_gap_ms` | 750 | ms, >=500 | int, exact |
| `reference_calibration_speech_pct`, `reference_student_speech_pct` | 60, 60 | %, 0..100 | int, exact |
| `reference_min_rms_x16` | 64 | x16, 0..65535 | Q12.4; 64 = 4 ADC RMS |
| `reference_min_pairs`, `reference_max_pairs` | 20, 64 | windows; 20 <= min <= max <=64 | int, invalid rejected |
| `reference_relative_margin_pct` | 25 | %, 0..100 | int; exact rational factor (100+pct)/100 |
| `reference_abs_margin_x16` | 64 | x16, 0..65535 | Q12.4; 4 ADC RMS |
| `reference_talking_pct` | 50 | %, 1..100 | int; cross multiply against known count |
| `reference_min_known_windows` | 4 | windows, >=1 | int; otherwise rolling UNKNOWN / probability fallback |
| `audio_smooth_ms`, `motion_window_ms` | 10000, 60000 | ms, >=0 | int; inclusive cutoff |
| `motion_min_pct`, `voice_min_pct` | 10, 40 | %, 0..100 | int; inclusive comparisons of sums |
| `co2_occupied_ppm` | 800 | ppm, 0..65535 | int; only retains occupancy |
| `occupied_after_ms`, `empty_after_ms` | 20000, 600000 | ms, >=0 | int dwell |
| `lecturer_zone_speech_pct` | 50 | %, 0..100 | int; inclusive, reference zone only; legacy JSON key `lecture_speech_pct` is deprecated |
| `conversation_enter_pct`, `conversation_exit_pct` | 40, 25 | %, 0..100 | int; inclusive; quieter exit hysteresis |
| `quiet_work_conversation_enter_pct`, `quiet_work_conversation_exit_pct` | 25, 15 | %, 0..100 | int; inclusive |
| `widespread_pct` | 50 | %, 0..100 | int; talking student zones *100 >= threshold * student zones with audio |
| `activity_dwell_ms`, `chatter_after_ms` | 20000, 120000 | ms, >=0 | int dwell |
| `co2_poor_ppm`, `co2_recovered_ppm` | 1200, 1000 | ppm, 0..65535 | int; enters >= poor, recovers < recovered |
| `air_dwell_ms`, `comfort_dwell_ms` | 60000, 60000 | ms, >=0 | int dwell; initial valid environment state immediate |
| `temp_min_x10`, `temp_max_x10` | 200, 280 | tenths °C, -32768..32767, min <= max | int bounds; outside comparisons strict |
| `humidity_min_x10`, `humidity_max_x10` | 300, 700 | tenths %RH, 0..1000, min <= max | int bounds; outside comparisons strict |
| `temp_hysteresis_x10`, `humidity_hysteresis_x10` | 5, 30 | tenths °C / tenths %RH, >=0, twice margin <= range width | int; must recover inside range by margin |
| `zone_dwell_ms` | 10000 | ms, >=0 | int; activity/air/comfort independent zone dwell; missing data immediate |

`ReferenceConfig` uses the corresponding field names without `reference_`.
Its nonnumeric keys are configured through `FusionConfig`: `zones`, `front_zones`,
`mode`, `reference_zone` (null disables comparison) and `zone_layout`. The legacy
`front_zones` key is accepted; only `reference_zone` determines the lecturer role.
If layout is omitted,
configured zones are placed in mapping order on a two-column grid; the default
map is A [0,0], B [0,1], C [1,0], D [1,1]. Explicit layouts must place all zones.

## Reference power-domain decision

Let `x = ref_rms_x16²`, `y = local_rms_x16²`, `N` be pair count,
`D = N*sum(x²) - sum(x)²`, and `C = N*sum(x*y) - sum(x)*sum(y)`.
The fit uses nonnegative `C`, then rounds gain `C*65536 / D` and intercept
`(sum(y)*D - C*sum(x)) / (N*D)` with integer `round_ratio`. If the intercept is
negative, set it to zero and refit gain using `sum(x*y) / sum(x²)`. These divisions
are exact rational descriptions; code computes integer quotients and remainders.
The original relative-variance gate is exactly `D*1000000 <= sum(x)²`.

`expected = (gain_q16 * ref_rms_x16² >> 16) + background_power_x256`.
For the default 25% margin, a strong level candidate requires:

```
adjusted = local_rms_x16 - abs_margin_x16
adjusted > 0 and adjusted**2 * 16 > (expected + upper_residual_x256) * 25
```

Other integer percentage margins reduce `(100 + pct)/100` by gcd, then square
its numerator and denominator. Speech evidence, two-window onset, one-window hold
and gap handling are unchanged. No square root participates in this decision.

Baseline JSON is now **version 2**, with Q16 gain and power_x256 coefficients.
Float version 1 files are rejected: recalibrate rather than silently change units.
Loading restores no clocks, queues or alert; integer profile/map must match.

## Presentation and API

`FusionEngine.state()` contains only integers, booleans, strings, lists, maps and
null. Events use `time_ms`; probabilities use `probs_pct`; confidence and smoothed
reference share use `confidence_pct` and `talking_pct`. Every configured zone has
activity, air, comfort, ONLINE/STALE/OFFLINE status, node ID, layout, reference
marker and scaled metrics. Rounded metrics never feed the statecharts.

`dashboard.present_classroom` / `present_reference` add human decimal temperature,
humidity, gain and RMS fields to the JSON. Only these display functions use
`math.isqrt` to show expected RMS and a threshold, rounded down to one Q12.4 step
before dividing by 16. The displayed threshold is rounded, so a client must use
the documented integer inequality to reproduce decisions. Existing reference
status tooltips keep their decimal field names; raw scaled fields also remain.

The heatmap shows activity, CO₂, temperature/comfort or motion. Text and icons
accompany colour. Reference/front markers persist; stale cells dim and offline
cells hatch. Buttons are keyboard-operable and expose `aria-pressed` state.

## Sparse reporting and rolling reference evidence

PENDING already satisfies the excess-level inequality and the speech gate, so it
counts as positive evidence in the 10-second smoother along with TALKING/HOLD.
QUIET is negative; UNKNOWN/calibration are excluded. Raw two-window onset remains
available as diagnostic state, but does not gate the rolling result a second time.

The gateway supplies each node's **applied** `report_interval_ms` (protocol range
200..10000) to `FusionEngine.add`. Pure Python callers must supply this keyword
when departing from the default 1000 ms. Rolling `freshness_ms` is:

```
max(reference_max_age_ms,
    max(student_report_interval_ms, reference_report_interval_ms)
    + 500 + reference_pair_tolerance_ms)
```

All terms are integer ms. The older paired entry can already be 500 ms old when
its batch arrives, and tolerance provides jitter headroom. With 2000 ms reports,
the default limit is 2750 ms. A fixed 1500 ms cutoff previously forced UNKNOWN
between every report, interrupting classroom dwell. The raw reference module's
1500 ms expiry and strict pair tolerance are unchanged. Offline/stale nodes still
force fallback immediately; the 10-second smoothing window and four-known-window
minimum still apply. Extremely sparse reports can lack enough evidence and use
probabilities instead: this does not promise detection at every interval up to
10000 ms. One-second reports preserve more windows and remain recommended.

A realistic 2000 ms regression uses reference audio/report phases 0.00/0.40 s,
student phases 0.35/0.65 s, uniform 0–80 ms jitter, and seeds 1/2/7. For seed 1,
before the fix NOISE_RISING never occurred and rolling TALKING covered 2.13% of
the 150-second student-talking phase. Counting PENDING alone raised coverage to
60.53%, but still never completed classroom dwell. With cadence-aware freshness,
coverage reaches 95.83% and NOISE_RISING occurs after 26.25 s. Lecture-only
smoothed TALKING time is 2.79% (including release tail), raw TALKING windows 0%,
and positive PENDING/TALKING paired windows 0.61%,
and there are no new lecture-only NOISE_RISING entries. These are simulated
metrics, not measured physical-classroom performance.

## Configuration renames

| Old JSON name | New JSON name | Value conversion |
|---|---|---|
| `reference_pair_tolerance_s`, `reference_max_age_s`, `reference_max_gap_s` | `reference_pair_tolerance_ms`, `reference_max_age_ms`, `reference_max_gap_ms` | seconds *1000 |
| `audio_smooth_s`, `motion_window_s` | `audio_smooth_ms`, `motion_window_ms` | seconds *1000 |
| `occupied_after_s`, `empty_after_s` | `occupied_after_ms`, `empty_after_ms` | seconds *1000 |
| `activity_dwell_s`, `chatter_after_s`, `air_dwell_s`, `comfort_dwell_s` | `activity_dwell_ms`, `chatter_after_ms`, `air_dwell_ms`, `comfort_dwell_ms` | seconds *1000 |
| `motion_pct_min`, `voice_pct_min` | `motion_min_pct`, `voice_min_pct` | same integer percentage |
| `reference_min_rms`, `reference_absolute_margin` | `reference_min_rms_x16`, `reference_abs_margin_x16` | ADC units *16 |
| `reference_relative_margin`, `reference_talking_fraction`, `widespread_fraction` | `reference_relative_margin_pct`, `reference_talking_pct`, `widespread_pct` | fraction *100 |
| `temp_min_c`, `temp_max_c`, `temp_hysteresis_c` | `temp_min_x10`, `temp_max_x10`, `temp_hysteresis_x10` | °C *10 |
| `humidity_min_pct`, `humidity_max_pct`, `humidity_hysteresis_pct` | `humidity_min_x10`, `humidity_max_x10`, `humidity_hysteresis_x10` | %RH *10 |

Other existing keys are unchanged. `zone_dwell_ms` and `zone_layout` are new.

## Enforcement and accuracy evidence

Run from `pc/`: `python3 -m unittest`.

`tests/test_integer_enforcement.py` parses both source files with `ast`, rejecting
float/complex constants, `/`, `/=`, fractional/negative powers, float/complex
construction, decimal telemetry accessors, noninteger `math` operations (sqrt,
exp, log, trigonometry etc.), numeric import shortcuts and dynamic evaluation.
It prints this reviewable allow-list:

```
reference.py: seconds_to_ms
fusion.py:    (none)
```

This narrow static guard is backed by tests recursively inspecting live engine
state/histories and exercising exact decision boundaries, rounding, full-width
RMS powers and environment saturation. It is not a general Python security proof.
The frozen float implementation lives only in `tests/float_reference/`, never in
`mosaic` imports. It is the committed pre-integer implementation from `965d1a8`;
only its reference import changes to be package-relative. SHA-256 hashes of the
original files are checked in `tests/test_integer_accuracy.py`. A test-only
adapter applies the current location-based speech rules to the baseline's float
means and dwell. The frozen files retain their original class names and logic.

The accuracy test feeds **all seven simulator scenarios**, seeds **1, 2, 7**,
default 1000 ms reports, independent audio/report phases, +/-100 ppm audio drift and uniform **0–80 ms**
receive jitter to both engines using identical datagrams and evaluation times.
It explicitly calibrates the reference scenario and also runs the discussion
scenario in DISCUSSION mode: **24 complete runs**. It collects every transition,
including those beyond the bounded event history. Acceptance: same states in the
same order in each region, with **every transition within 1000 ms**.

| Region | States in same order in every run? | Transitions compared | Maximum absolute time difference |
|---|---|---:|---:|
| Activity | Yes | 93 | 500.000 ms |
| Air | Yes | 36 | 0.391 ms |
| Comfort | Yes | 36 | 0.417 ms |

The maximum activity difference is one audio window (500 ms), including the
team's requested change to count PENDING as positive evidence; the frozen float
oracle retains its original TALKING-only policy. Air and comfort differences
are below 1 ms because the integer engine rounds timestamps to the nearest ms.
No classroom state sequence differed between engines in these runs. This bounds
tested scenarios, not every possible acoustic
signal: Q16 coefficient quantisation can change a result extremely near a gate.

Browser evidence is saved under `docs/evidence/integer-fusion-zones/` for the live
reference and lecture scenarios, light/dark and phone width. Physical Pico and
real-classroom accuracy/timing remain **UNVERIFIED**.
