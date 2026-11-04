# Fault Table

Every fault MOSAIC is designed to survive: how it is detected, what the system does, what the
PC shows, and how it recovers. **Status** is honest about the code on `main` (plus PR #6 for the
node firmware):

| Status | Meaning |
|--------|---------|
| ✅ Implemented | In the code, with a test or a named code path as evidence |
| 🟡 Partial | Detected or reported, but not fully handled, or not yet tested on hardware |
| 🔴 Gap | Not handled yet; owner and plan given |

Hardware checks referenced as `N5`, `N9` etc. are in [week10_test_plan.md](week10_test_plan.md).
Principle throughout: **a bad or missing value is marked invalid and never fused**. The node
clears the value's `valid_flags` bit, and the PC ignores invalid fields and offline nodes.

## Sensors (node, Kendrick)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence |
|----|-------|-------------|----------|----------|----------|--------|----------|
| S1 | DHT22 does not respond | PIO capture timeout → `SENSOR_TIMEOUT` | Temperature/humidity marked invalid | `—` on the card; Comfort *No data* if no zone has a valid reading | Next read after `dht_interval_ms` (2.5 s) | ✅ | `dht22.c`, `environment.c`; `firmware/tests/environment_host_test.c` |
| S2 | DHT22 checksum error | Byte sum ≠ checksum → `SENSOR_CHECKSUM_ERROR` | As S1 | As S1 | Next read | ✅ | `environment.c` decode |
| S3 | DHT22 impossible value | Outside −40…80 °C or > 100 %RH → `SENSOR_OUT_OF_RANGE` | As S1; the value is not used | As S1 | Next read | ✅ | `environment.c` decode |
| S4 | DHT22 reading too old | No good read for 6 s → `SENSOR_STALE` | As S1 | As S1 | Next good read | ✅ | `environment_expire()` |
| S5 | DHT22 PIO/DMA unavailable at boot | `dht22_init()` fails → `SENSOR_RESOURCE_ERROR` | Node keeps running with CO₂ and PIR | As S1 | Reboot | ✅ | `node_main.c` (`dht_ready`) |
| S6 | CO₂ sensor warming up (first 120 s) | ACD1100 warm-up timer | `CO2_WARMUP` flag; value not used | *Warming up*; Air *No data* | Automatic after warm-up | ✅ | `sensors.c`; `test_fusion.py` `test_warming_up_is_unknown` |
| S7 | CO₂ UART silent, bad frame or checksum | `SENSOR_TIMEOUT` / `PROTOCOL_ERROR` / `CHECKSUM_ERROR` | CO₂ marked invalid | `—`; Air *No data* if no zone is valid | Next request (`co2_interval_ms`) | ✅ | `sensors.c`, `environment.c` |
| S8 | CO₂ reading too old | No good read for 5 s → `SENSOR_STALE` | As S7 | As S7 | Next good read | ✅ | `environment_expire()` |
| S9 | PIR not sampled | No sample for 1 s → invalid | PIR marked invalid | `—` | Next sample (100 ms) | ✅ | `environment_expire()` |
| S10 | PIR reads "no motion" in an occupied room (still class) | Design: PIR is motion, not presence | Fusion also uses voices and raised CO₂ as evidence; Empty needs 10 min of no evidence | Stays *Occupied* | n/a | ✅ | `fusion.py`; `test_fusion.py` `test_still_class_stays_occupied`; `exam` scenario |

## Audio (node, Moe and Darius)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence / plan |
|----|-------|-------------|----------|----------|----------|--------|-----------------|
| A1 | Microphone signal too weak (no preamp, bad bias) | Not detected on the node today | n/a | Audio looks like silence | Hardware fix (preamp) | 🔴 | Bench check B1 first. Darius's branch has a `LOW_LEVEL` check to bring in. |
| A2 | Microphone clipping | Not detected on `main` | n/a | n/a | Lower the gain via CONFIG `audio_gain_x256` | 🔴 | Darius's branch has a `CLIPPED` check; port it with the audio task |
| A3 | Window not processed before the next one (overrun) | Protocol field `audio_overruns` | Window dropped and counted | Overrun count; skipped windows from `audio_window_seq` | Automatic, next window | 🟡 | Protocol and PC ready; node audio task not written yet (Arif/Moe) |
| A4 | Classifier unsure | Best probability < `audio_conf_threshold_pct` | Reports `UNKNOWN`, all probabilities still sent | *Unsure*; fusion averages probabilities over 10 s | Automatic | 🟡 | Protocol and PC ready; node classifier pending (Darius) |
| A5 | Single transient (cough, bang, dropped book) | Fusion smoothing (10 s) + dwell time (20 s) | Ignored | No state change | n/a | ✅ | `test_fusion.py` `test_transient_noise_ignored` |
| A6 | Gap between capture windows | Design limitation: capture stops after each 8,000-sample window | Audio is sampled, not continuous | n/a | n/a | 🟡 | `audio_capture.c` `dma_handler`. Moving to double-buffered DMA makes it continuous. |

## Node system (Arif)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence / plan |
|----|-------|-------------|----------|----------|----------|--------|-----------------|
| N1 | A task hangs | Hardware watchdog (8 s), fed only when every task has reported alive | Reset | Node reboots (see N2) | Reboot | 🔴 | Planned with FreeRTOS. The alive rule must not reset the node while Wi-Fi is rejoining (Week 6 feedback). |
| N2 | Node reboots or loses power | `FIRST_SINCE_BOOT` flag + `seq` restarting | PC counts a reboot (not packet loss) and re-sends the node's CONFIG | Reboot count; config re-applied | Automatic | ✅ | `gateway.py` `_track_seq`, `_check_config`; `test_gateway.py` reboot and `test_resends_after_reboot`; hardware check N8 |
| N3 | Memory running low | `free_heap_bytes` in every TELEMETRY | Reported only | Logged in CSV | n/a | 🟡 | Monitoring only; no threshold or action yet |
| N4 | Wi-Fi chip fails, or credentials/PC IP not built in | `cyw43_arch_init()` result; empty settings | Node runs sensors only and says why on serial | Node never appears | Fix config, rebuild | ✅ | `node_main.c` start-up |

## Network (Arif and ZhiHao)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence |
|----|-------|-------------|----------|----------|----------|--------|----------|
| W1 | Wi-Fi drops | Node: link status. PC: no TELEMETRY for 3 reports / 10 s | Node keeps sensing and rejoins every 15 s. PC marks *Stale*, then *Offline*. Fusion ignores offline zones and lowers confidence | *Stale* → *Offline*; confidence drops | Automatic on rejoin | 🟡 | `node_main.c` `wifi_service`; `gateway.py` `NodeState.status`; `test_fusion.py` `test_offline_zones`. Hardware check N9 not run yet. |
| W2 | Packets lost | Gaps in `seq` | Counted per node; the next report supersedes (UDP) | Loss % per node | Automatic | ✅ | `test_gateway.py` loss tests |
| W3 | Duplicate packets | Same `seq` twice | Counted, not double-processed | Duplicate count | n/a | ✅ | `test_gateway.py` |
| W4 | Malformed or foreign datagram | Magic, version, type or length check | Dropped; PC counts per source IP | Dropped count | n/a | ✅ | `mosaic_header_check()`; `test_protocol.py` `Malformed`; `test_gateway.py` `test_malformed_dropped_per_source` |
| W5 | Old-protocol (v1) device | `version` ≠ 2 | Dropped as unsupported | Dropped count | Reflash | ✅ | `test_protocol.py` `test_wrong_version` |
| W6 | PC unreachable | `udp_sendto` fails | Node keeps sensing; a failed send doesn't use up a `seq` | Node absent | Automatic when the PC is back | ✅ | `node_main.c` `send_to_pc` |

## Configuration (ZhiHao)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence |
|----|-------|-------------|----------|----------|----------|--------|----------|
| C1 | CONFIG or its ACK lost | No matching ACK | Re-sent every 500 ms, up to 5 times. A TELEMETRY already showing the new version counts as applied | Delivery *sending* → *applied* | Automatic | ✅ | `test_gateway.py` `test_retries_then_fails`, `test_lost_ack_but_telemetry_shows_version` |
| C2 | Out-of-range setting | PC: `Config.check()` before sending. Node: `mosaic_config_check()` | PC refuses (HTTP 400). Node replies `INVALID_VALUE` and applies **nothing** | Error message | n/a | ✅ | `test_protocol.py` `ConfigRanges`; `test_dashboard.py` `test_bad_requests`; hardware check N6 |
| C3 | Old or replayed CONFIG | `config_version` lower than applied | Node replies `STALE_VERSION` and applies nothing | — | n/a | ✅ | `test_protocol.py` `test_version_ordering`; `protocol_dump.c` |
| C4 | CONFIG from another device, or for another node | Source IP ≠ `MOSAIC_PC_IP`, or `node_id` ≠ own ID | Silently dropped | — | n/a | 🟡 | `node_main.c` `on_receive`; simulator test `test_simulated_node_checks_config`. Hardware check N7 not run yet. |
| C5 | Node never acknowledges | 5 sends without an ACK | Delivery *failed*; retried after 10 s while the node still reports | *Failed* | Automatic | ✅ | `test_gateway.py` `test_failed_retries_after_wait` |
| C6 | PC restarts and counts versions from 1 again | Node replies `STALE_VERSION` | PC jumps past the node's reported version and re-sends | Applied | Automatic | ✅ | `test_gateway.py` `test_stale_version_jumps_past_node` |
| C7 | Attacker spoofs the PC's IP | Not detected | — | — | — | 🟡 | **Accepted risk** for a classroom prototype. A shared-key MAC on CONFIG is deferred (`docs/protocol.md` §8). |

## PC and fusion (ZhiHao)

| ID | Fault | Detected by | Response | PC shows | Recovery | Status | Evidence |
|----|-------|-------------|----------|----------|----------|--------|----------|
| F1 | No zone reporting | No online/stale nodes | All regions go to *Unknown* immediately | *No data* | When data returns (with dwell) | ✅ | `test_fusion.py` `test_offline_zones` |
| F2 | Some zones stale or missing | Gateway node status | Stale zones count half; missing zones lower confidence | Confidence % | Automatic | ✅ | `fusion.py` `evaluate()` |
| F3 | Reading hovers at a threshold | Separate enter/exit thresholds (hysteresis) + dwell | State does not flicker | Stable state | n/a | ✅ | `test_fusion.py` murmur, ventilation and comfort tests |
| F4 | Fusion thresholds are wrong for the room | Scenario tests | Thresholds are tunable without code (`--fusion-config`) | n/a | Re-tune | 🟡 | `test_scenarios.py`; real classroom tuning still to do |
| F5 | Reference node offline or not calibrated | — | Student zones fall back to the probability-based rule | Reference status | Calibrate | 🟡 | In progress (reference-comparison PR) |
| F6 | Gateway/dashboard crashes | Process exits | Nodes keep sensing and sending; the CSV log is appended on restart; nodes' config is re-sent on mismatch | Gap in the log | Restart the dashboard | 🟡 | No auto-restart; acceptable for a supervised demo |

## Summary of gaps (owners)

| Gap | Owner | Plan |
|-----|-------|------|
| N1 Watchdog | Arif | With FreeRTOS. Alive bits per task; Wi-Fi rejoin must not starve the watchdog. |
| A1/A2 Mic too weak / clipping | Darius, Moe | Bench check B1 now. Port `LOW_LEVEL` and `CLIPPED` checks from Darius's branch into the audio task. |
| A3/A4 Overruns, unsure class on the node | Moe, Darius, Arif | Comes with wiring audio into the node |
| W1, C4 Hardware confirmation | Arif, ZhiHao | Week 10 checks N7 and N9 |
