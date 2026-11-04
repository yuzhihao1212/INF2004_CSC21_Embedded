# Evaluating a MOSAIC capture

From `pc/`, capture both streams together:

```sh
python3 -m mosaic.gateway --csv /tmp/run.csv --events /tmp/run.jsonl
# Or include the dashboard and four scripted nodes:
python3 -m mosaic.dashboard --scenario lecture --csv /tmp/run.csv --events /tmp/run.jsonl
```

Stop with Ctrl+C so `run_end` closes the observation interval. Evaluate:

```sh
python3 -m mosaic.evaluate /tmp/run.csv --events /tmp/run.jsonl \
  --out /tmp/report.md --json /tmp/summary.json --deadline-ms 400
python3 -m mosaic.evaluate /tmp/run.csv --events /tmp/run.jsonl \
  --expected ../docs/lecture_expected.csv --out /tmp/scored.md --json /tmp/scored.json
```

The lecture scenario lasts 450 s. The example labels are **script-derived stable
windows**, not human measurements or an accuracy claim; gaps intentionally leave
startup and dwell transitions unscored. Replace them with independent human
annotations for a real accuracy evaluation. Times start at the event session's
`run_start`, not at a Pico timestamp. A short capture only scores overlapping
labels and reports the actual number of labelled seconds. Regions are `activity`,
`air`, `comfort`, `mode`, or `zone:<label>:activity|air|comfort`.

## What is logged

`--events FILE` appends UTF-8 JSON Lines. Each entry has `schema_version: 1`, a
random `session` identifier, UTC ISO `wall_time`, integer `monotonic_ms` and `event`:

| Event | Additional fields |
|---|---|
| `run_start`, `run_end` | Start also includes the configured node/zone map |
| `datagram` | Every accepted TELEMETRY/PONG/CONFIG_ACK: node, source_ip, msg_type, seq, flags, sender_time_ms; telemetry includes csv_pc_time |
| `pong` | node, rtt_ms |
| `node_status` | node, old, new (ONLINE/STALE/OFFLINE) |
| `config` | node, state (sending/applied/failed/rejected/stale), config_version, report_interval_ms, optional attempt/ack_status/reason |
| `fusion` | region, old, new, reason; initial classroom states are included |
| `zone_state` | node, zone, region, old, new; initial zone states are included |
| `reference` | zone, action (start/ready/reset); ready includes pairs and gain_q16 |
| `drop` | source_ip, bytes; malformed or unexpected datagrams |

All events are flushed when written. The original CSV header, field ordering,
units, naive local ISO `pc_time` format and semicolon audio lists are unchanged.
The event's `csv_pc_time` joins telemetry to its receive-clock timestamp without
changing CSV columns. Monotonic durations survive wall-clock corrections. Raw
accepted headers are needed because the node increments `seq` for PONG/ACK too;
logging only telemetry would falsely count these messages as packet loss.

Separate appended runs have separate session IDs. Evaluation sums recorded
session durations and does not infer loss or report intervals between runs.
Expected-timeline scoring requires exactly one session to keep its time origin
unambiguous. Use new file names for each labelled hardware experiment. An absent
`run_end` is right-censored at the final observation, not extended into an unknown
period. CSV/event mismatches, malformed rows and overlapping labels are errors.

## Metric definitions and limits

- **Packet counters** call the same `Gateway.track_header` / `_track_seq` logic as
  live reception, including uint32 sequence wrap, duplicates and reboot flags.
  Reordering is interpreted as a reboot by that existing policy. No packets before
  first observation or after the final observation are assumed missing; trailing
  silence is visible in availability rather than inferred packet counts. Delivery/loss percentages match
  `NodeState.loss_pct`: received includes duplicates. JSON also provides
  `unique_delivery_pct` / `unique_loss_pct`, excluding duplicates from received
  and expected totals; Markdown shows these alongside the gateway loss metric.
  Overall ratios use summed counters, not averages of percentages.
- **CSV-only loss** is explicitly an estimate: omitted PONG/ACKs can look like
  gaps. RTT, availability, recovery and fusion occupancy need events and are shown
  as unavailable without them. Empty samples are null/—, never invented zeroes.
- **Report interval** is the receive-time difference between unique telemetry
  reports from the same node/session/boot. Duplicates and reboot boundaries are
  excluded. Jitter is p95 minus p50, in ms. Overall pools these per-node intervals,
  not the intervals between different nodes' arrivals.
- **Percentiles** use `statistics.quantiles(n=100, method='inclusive')`. The minimum
  and maximum are the endpoints; singleton samples repeat their only value. Small
  sample counts are retained in JSON; do not infer a reliable tail from a few
  packets. DSP/inference statistics describe the reported **maxima per interval**,
  rather than the distribution of individual windows.
- **Deadline flags** compare `dsp_time_us + inference_time_us > deadline_ms*1000`.
  The two maxima can refer to different windows. The report therefore gives
  flagged reports and the number of their received windows as an **upper bound**;
  exact per-window miss counts are **UNVERIFIED**, not falsely reported as a
  measurement. These fields do not include unspecified scheduling/transport work.
- **Audio received** deduplicates duplicate packets and overlapping audio windows.
  Skips are `max(0, (seq-current - seq-previous) mod 65536 - window_count)`, within
  a boot; the first observation is only a baseline. Overruns use uint16 counter
  increases within a boot. Initial counters and reboots are not counted as new
  overruns. Multiple full counter wraps between observations cannot be recovered.
- **RTT** uses PONG observations; negative observations stay in the raw log but are
  excluded from statistics with a note. No synchronised-clock or one-way-delay
  claim is made. **Recovery** is the observed OFFLINE→ONLINE duration after an
  outage; initial discovery and unfinished outages are not successful recoveries.
- **Availability** integrates recorded status intervals. The configured map starts
  OFFLINE until first contact. The live `NodeState.status` policy is unchanged;
  any accepted datagram refreshes last_seen. Sampling is limited by the gateway
  poll interval (normally up to 200 ms) and scheduler stalls. Missing status
  history is UNOBSERVED; it must not be counted as ONLINE. Overall weights by
  node-seconds, not a simple mean of percentages.
- **CO₂ warm-up** measures first observed warm-up to first valid CO₂ report. It
  does not know the actual power-on instant. Unfinished/reboot-interrupted episodes
  report observed lower bounds, not a completed warm-up duration. Overall sums
  node-seconds; this is not a classroom wall-clock duration.
- **Fusion** integrates stepwise states through session end. Initial snapshots do
  not count as transitions; changes include their relative time and reason. Zone
  activity/air/comfort are independent regions. Evaluation reads logged decisions
  and never recomputes or changes the integer fusion algorithm.
- **Recognition scoring** integrates duration rather than counting reports. Each
  region is scored only on labelled intervals clipped to the capture; unlabelled
  gaps are ignored. Wrong/unobserved decisions are incorrect. Each multiclass
  error contributes one false-positive interval for the actual state and one
  false-negative interval for the expected state. JSON and Markdown include
  per-state one-vs-rest TP/FP/FN seconds. Overall accuracy weights labelled
  region-seconds; labels for multiple regions can overlap in wall-clock time.

These tools produce evidence from what was recorded. Simulator timings and labels
are synthetic; hardware latency, recovery, DSP deadlines and recognition accuracy
remain **UNVERIFIED** until tested with real devices and independent labels.
The floating-point arithmetic here is offline statistical reporting; the protected
integer fusion/reference processing paths are unchanged.
