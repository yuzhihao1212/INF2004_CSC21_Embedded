# Team and subsystems

The tables describe the current subsystem claims and the retained template
code, which is marked *example*. Keep the claims current as the code changes.

Fill this in at the start of the project and keep it up to date. It is the
single place that says **who owns what**, so that five people can work in
one firmware image without clashing over pins, priorities, or kernel objects.

A **subsystem** is one student's part of the product, with its own folder.
It may contain several tasks and own several peripherals (see section 3).

Rule: **only the owner edits a subsystem's folders.** To change another
subsystem, ask its owner or open a pull request for them to review.

## 1. Members and subsystems

| # | Subsystem (what it does) | Student ID | GitHub username | Code | Tests |
|---|---|---|---|---|---|
| 1 | Audio capture and fixed-point DSP: samples the microphone, produces the feature windows (Moe) | 2500112 | mmmmm0e | `app_program/subsystem1/` | `testing/subsystem1/` |
| 2 | int8 classifier: classifies audio windows as speech, background or transient noise; output may be UNKNOWN for invalid, low-level, clipped, pending or timing-fault conditions (Darius) | 2501046 | Dkkan-dev | `app_program/subsystem2/` | `testing/subsystem2/` |
| 3 | Environment sensors: DHT22, CO₂ (ACD1100), PIR (Kendrick) | 2500144 | kthgoat | `app_program/subsystem3/` | `testing/subsystem3/` |
| 4 | Networking and node health: Wi-Fi and the MQTT link to the PC; a supervisor task checks that the audio, classifier, environment and report tasks keep making progress. The hardware watchdog it feeds is built but switched off (timeout 0): its timing tests S4-U04 to U06 were not run (Arif) | 2500768 | arifkareem | `app_program/subsystem4/` | `testing/subsystem4/` |
| 5 | Node config and telemetry: applies CONFIG from the PC, builds each report (ZhiHao) | 2503001 | yuzhihao1212 | `app_program/subsystem5/` | `testing/subsystem5/` |

The production audio, classifier, environment, networking and telemetry paths are
implemented alongside the retained template LED, producer, consumer and monitor
examples. Implementation in source does not establish final hardware validation.

Shared files (`app_program/app_main.c`, `app_program/app.h`, this file)
are changed only by agreement of the team. The exception is claiming an empty
row in this file (a pin, a peripheral, an interface ID), which anyone may do
(section 2).

## 2. Pins

One owner per pin. Claim a pin here **before** you wire or code it.

**Why:** two subsystems using the same pin is one of the most common and
hardest-to-find mistakes in a team project. The code builds without any
error, but the hardware misbehaves. Each subsystem can pass its own tests
and then fail once they are combined, and two outputs driving the same pin
against each other can damage it. Writing the claim down first means a clash
is spotted when someone edits this table, not hours later on the bench.

**No instructor check needed.** The team keeps this table itself. You do not
need the instructor, or the rest of the team, to check or approve a claim:
if the row is empty, fill it in and commit. If two people claim the same
pin, they agree between themselves who moves. Only the *reserved* rows are
fixed.

| Pin | Owner | Used for |
|---|---|---|
| GP23, GP24, GP25, GP29 | *reserved* | Pico W radio |
| GP0 | | (taken whenever the team builds with `CRASH_REPORT=1`) |
| GP1 | | (taken whenever the team builds with `CRASH_REPORT=1`) |
| GP2 | S3 | DHT22 open-drain DATA, environment_task |
| GP3 | | |
| GP4 | | |
| GP5 | | |
| GP6 | | |
| GP7 | | |
| GP8 | S3 | ACD1100 UART1 TX, environment_task |
| GP9 | S3 | ACD1100 UART1 RX, environment_task |
| GP10 | | |
| GP11 | | |
| GP12 | | |
| GP13 | | |
| GP14 | | |
| GP15 | | |
| GP16 | S3 | PIR input, owned by `environment_task` |
| GP17 | | |
| GP18 | | |
| GP19 | *example:* S1 | external LED (LED + 330 Ω to GND) |
| GP20 | | |
| GP21 | | |
| GP22 | | |
| GP26 | S1 (Moe) | Microphone AUD, ADC0, 16 kHz |
| GP27 | | (ADC1 capable) |
| GP28 | | (ADC2 capable) |

## 3. Peripherals

**Subsystems, tasks and peripherals are three different things:**

| Term | What it is | Example |
|---|---|---|
| **Subsystem** | one student's part of the product, one folder | "environment sensing", "motor control", "user interface" |
| **Task** | one thread of execution. A subsystem may have **as many tasks as it needs** | a sampling task and a filtering task, both in "environment sensing" |
| **Peripheral** | one hardware block on the RP2040 | I2C0, UART1, the ADC |

A driver is **not** a subsystem. It is code *inside* the subsystem that
needs that hardware: the "environment sensing" subsystem contains the I2C
sensor code, and owns I2C0. Write it as `drv_<name>.c` / `drv_<name>.h` in
that subsystem's folder, never under `device/`, and call it only from the
peripheral's owning task. The kernel's own drivers in `device/` (serial,
I2C, ADC) may be used instead; switching one on in `config/config_device.h`
changes shared configuration, so record it in the table below first.

**The rule: each peripheral is driven by exactly one task, its *owning
task*.** That task can be in any subsystem, and one subsystem may own
several peripherals (one owning task each, or one task owning all of them).
Every other task, in the same subsystem or another one, asks the owning task
through a kernel object (section 5) and never touches that peripheral itself.

*Why:* this port runs tasks on both cores at the same time. If two tasks
drive the same I2C or UART block at once, their transfers get mixed up, and
the drivers have no locking to stop it.

| Peripheral | Owner subsystem | Owning task | Pins |
|---|---|---|---|
| UART1 | S3 | `environment_task` (polled 1200 8N1) | GP8/GP9 |
| One PIO SM + 20 instruction words, dynamically claimed | S3 | `environment_task`; shared SDK allocator, no fixed PIO/SM | GP2 |
| One DMA channel, dynamically claimed | S3 | `environment_task`; shared SDK allocator, IRQs disabled for this channel | GP2 via PIO RX |
| I2C0 | | | |
| I2C1 | | | |
| SPI0 | | | |
| SPI1 | | | |
| ADC | S1 (Moe) | audio_task, core 0 | GP26; no other task opens the kernel ADC device |
| RP2040 watchdog | S4 (Arif) | `s4_health_task` | None |
| PWM slices (list) | | | |
| WiFi radio, TCP/IP, MQTT | *kernel* | `cyw43_utk_task` (built in) | GP23–25, GP29 |

### WiFi and MQTT are special

The radio and the network stack belong to the kernel's built-in WiFi service
task, `cyw43_utk_task` (`lib/libwifi/sysdepend/pico_rp2040/`). **No student
task may call `cyw43_...`, lwIP or MQTT functions, not even from a
"WiFi subsystem".** The calls are not safe from any other task, on either core.

What students *can* do:

- **Read the connection state** from any task, which is always safe:
  ```c
  #include "cyw43_utk.h"
  T_CYW43_UTK_STATUS st;
  cyw43_utk_get_status(&st);   /* st.ready, st.link_status, st.ip_addr, ... */
  ```
- **Send or receive data over the network** through the existing S4/S5 handoff.
  S5 queues telemetry, CONFIG_ACK and PONG; S4's functions let the MQTT client in
  `lib/liblwip/sysdepend/pico_rp2040/mqtt_utk.c` poll the queue with `TMO_POL`
  inside `cyw43_utk_task`. It publishes those packets on `mosaic/node/<id>/telemetry`.
  CONFIG and PING arrive on `mosaic/node/<id>/config` and are queued for S5.
  The PC gateway subscribes to telemetry and status and feeds fusion and the dashboard.
  This path needs `NET=lwip MQTT=1`; see the repository root README. Changes to shared
  library code still require agreement from the team and instructor. Source wiring is
  not evidence of a passed end-to-end or recovery test.

## 4. Task priorities

1 is the highest. 1–4 are used by the kernel (USB console 3, WiFi 4). Each subsystem gets its own band by default;
change it only by team agreement. Write down every task you create.

| Subsystem | Priority band | Tasks (name – priority – core) |
|---|---|---|
| 1 | 12–13 | *example:* led_task – 12 – any; audio_task – 13 – core 0, 4096-byte stack |
| 2 | 14–15 | *example:* producer_task – 14 – core 1; classifier_task – 15 – core 1, 4096-byte stack |
| 3 | 16–17 | consumer_task – 16 – core 0 (example compatibility); environment_task – 17 – core 0; TEST=1 observer – 17 – core 0, 4096-byte stack, self-deletes |
| 4 | 18–19 | *example:* monitor_task – 18 – any; `s4_health_task` – 19 – any |
| 5 | 20–21 | report_task – 20 – any |

For SMP=1, `TP_PRC1` = core 0, `TP_PRC2` = core 1, or "any". The
single-core build does not apply these affinities.

## 5. Interfaces between subsystems

Every arrow between two subsystems is listed here. The **provider** creates
the kernel object and publishes its ID in its own `subsystemN.h`; the **user** only
sends to it or waits on it. Agree on the data format before coding.

| ID | From → To | Mechanism | Object ID name | Data / meaning | Source status / agreement |
|---|---|---|---|---|---|
| IF-01 | S2 → S3 | mailbox (owned by S3) | `mbx_samples` | `SAMPLE_MSG` in `subsystem2.h` | *example* |
| IF-02 | S3 → S2 | semaphore + fixed memory pool (owned by S2) | `sem_slots`, `mpf_samples` | receiver returns the block, then 1 slot | *example* |
| IF-03 | S3 → S4 | message buffer + event flag (owned by S4) | `mbf_summary`, `flg_events` | text line ≤ `S4_SUMMARY_MAX` bytes, then `FLG_BATCH` | *example* |
| IF-04 | S4 → S3 | shared data under a mutex (owned by S3) | `app_stats`, `mtx_stats` | `APP_STATS`, read only while locked | *example* |
| IF-05 | S4 → S1 | task control | `tid_led` | `tk_sus_tsk` / `tk_rsm_tsk` / `tk_chg_pri` | *example* |
| IF-06 | S4 → S5 | message buffer (owned by S5) | `mbf_s5_rx` | One protocol v2 CONFIG/PING datagram, ≤128 bytes; S4 uses `TMO_POL` inside `cyw43_utk_task`, checks ID > 0 | wired in source; owners' review needed |
| IF-07 | S5 → S4 | message buffer (owned by S5) | `mbf_s5_tx` | One protocol v2 TELEMETRY/CONFIG_ACK/PONG, ≤64 bytes; S4 receives with `TMO_POL` inside `cyw43_utk_task`, checks ID > 0 | wired in source; owners' review needed |
| IF-08 | S3 → S5 | post function, S5 mutex | `mtx_s5` | `s5_post_environment(temp_x10, humidity_x10, co2_ppm, valid_bits)`; expires after 6000 ms | wired in source; owners' review needed |
| IF-09 | S3 → S5 | post function, S5 mutex | `mtx_s5` | `s5_post_pir(samples, active)`; interval counters, one sample or a batch | wired in source; owners' review needed |
| IF-10 | S2 → S5 | post functions, S5 mutex | `mtx_s5` | `s5_post_audio_window(window, dsp_us, inference_us)`, `s5_audio_dropped(windows)`; two consecutive windows, loss count | wired in source; owners' review needed |
| IF-11 | S4 → S5 | post function, S5 mutex | `mtx_s5` | `s5_post_health(rssi_dbm, cpu_load_pct, free_heap_bytes)` | API exists; no production poster found |
| IF-12 | S5 → S1/S3 | config getter, S5 mutex | `mtx_s5` | `s5_get_config(out)`; complete applied config snapshot for audio and sensor intervals | wired in source; owners' review needed |

Source status above describes implementation only. Validation requires recorded
test results, and agreement requires the relevant owners' sign-off; neither is
implied by source wiring. The integration log (`testing/integration/TEST_LOG.md`)
does not yet document a completed final-revision test for each production interface.

## 6. Kernel object budget

Limits are set in `config/config.h`. If the team needs more, raise the
limit there. The numbers below are the example's usage.

| Object | Limit | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|---|
| Task | 32 | 1 | 1 | 2 (+1 during TEST=1 observation) | 2 | 1 |
| Semaphore | 16 | | 1 | | | |
| Event flag | 16 | | | | 2 | |
| Mailbox | 12 | | | 1 | | |
| Mutex | 12 | | | 1 | | 1 |
| Message buffer | 12 | | | | 1 | 2 |
| Fixed memory pool | 12 | | 1 | | | |
| Variable memory pool | 12 | | | | | |
| Cyclic handler | 12 | 1 | | | | |
| Alarm handler | 12 | | | | 1 | |

(The kernel's USB and WiFi service tasks also use a few of these.)

## Audio/ML port resource claims (16 Nov 2026)

- S1: GP26/ADC0, audio task priority 13 on core 0, DMA IRQ1 (IRQ 12),
  one additional task and completion semaphore. Do not open the kernel ADC
  device while audio owns it. S1 does not change shared device configuration.
- DMA: Wi-Fi profiles use the existing SDK DMA allocator shared with CYW43;
  WIFI=none reserves channel 11. DMA IRQ1 is owned exclusively by S1.
- S2: classifier task priority 15 on core 1, one additional task and one
  message buffer, depth two. Both task stacks are 4096 bytes.
- IF-13, S1 -> S2: `mbf_audio_features`, owned by S2. Copied
  `audio_features_t` includes sequence, completion timestamp, 20 Q8 features,
  raw signal quality, confidence threshold and DSP duration. No raw pointers.
- IF-10: only S2 posts classified windows and ordered drop accounting to S5.
  Model classes background/speech/transient map to protocol IDs 1/2/4.
- Existing example tasks and interfaces remain until S3/S4 owners remove their
  dependencies. Their original object budget remains, plus the objects above.
- User authorized updating both S1 and S2 for this port on 16 Nov 2026.
