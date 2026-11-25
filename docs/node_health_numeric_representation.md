# Node-health numeric representation (Arif)

> **Historical record (status at hand-in, 25 Nov 2026).** Written on 10 Nov for the earlier FreeRTOS firmware: FreeRTOS ticks and stack words below do not describe the submitted µT-Kernel node. On the submitted node, task progress is supervised by `s4_health_task` and the watchdog is built but switched off. For the system as submitted, start at the [main README](../README.md) and the [evidence index](README.md).

Prepared 10 November 2026. This covers the node code, not DSP/model accuracy.

| Quantity | Representation / units | Behaviour / evidence |
|---|---|---|
| Task progress | unsigned bit mask; network=1, environment=2, optional audio=4 | Required mask is 3 or 7. A feed consumes all required bits together. A fast peer cannot replace missing progress. Actual C gate is exercised by `test_node_health.py` in both configurations. |
| Watchdog timeout | integer 8000 ms | Supervisor checks each 250 ms. Hardware task-stall logs show `last_reset=watchdog`; exact reset latency has not been measured. |
| Task scheduling | integer FreeRTOS ticks at 1000 Hz | Sensor period 2 ms, network 10 ms, supervisor 250 ms; `vTaskDelayUntil`. Audio producer owns its bounded window cadence. |
| Monotonic time | `uint64_t`, microseconds from SDK; milliseconds use integer division by 1000 | No float conversion. Packet sender time narrows to u32 milliseconds, with protocol wrap handling. |
| Free heap | u32 bytes on wire | RTOS uses `xPortGetFreeHeapSize`, minimum free heap in serial. It describes the 64 KiB kernel heap, not all unused SRAM. Observed 44176 bytes in supplied normal-run logs. |
| Stack headroom | FreeRTOS stack words (one word is 4 bytes on RP2040) | High-water marks are the minimum unused stack observed, not percentages or proof of all future paths. Reported separately per task; audio stack only exists when its source is supplied. |
| Send/retry/control counters | u32 counts in serial | Integer increments; may eventually wrap. Successful local submission is not proof of PC receipt. |
| Packet sequence | u32 messages, increments only on successful new submission | Retries retain original sequence/time/payload. PC handles wrap and duplicates. |
| Audio sequence | u16 windows, wraps | Handoff advances on each accepted window or explicit capture drop. No producer means zero windows. |
| Audio overrun/drop count | u16, saturates at 65535 | Includes producer-reported capture gaps, pending results discarded across a gap, bounded-buffer overflow and drained results whose first network submission fails. Local-send retry failures do not create new audio sequences. |
| DSP/inference timing | u32 microseconds | Producer supplies measured values. Per-report maxima reset after draining the handoff; maxima include overwritten windows in that interval. No fabricated timing while audio is absent. |
| Sensor numbers | i16 temperature x10, u16 humidity x10, integer ppm, integer PIR percentage | Existing environment conversion and validity ownership stays with Kendrick. |
| CPU load | u8 wire field, currently zero | Not measured. Zero must not be used as evidence of spare CPU capacity. |

No float arithmetic is introduced by the task-health gate, handoff or node-health
calculations above. SDK/driver code and DSP table initialization are separate
scope; this is not an assertion that the linked firmware contains no soft-float
helpers. PC display percentages are separate from these integer node values.

The C handoff test checks ordering, Q12.4 RMS preservation, maximum timing,
overflow, dropped-window gaps, sequence wrap, saturation and rejection of
out-of-range probabilities. Its emitted packet is decoded by the real Python
gateway in `test_node_audio_handoff.py`.
