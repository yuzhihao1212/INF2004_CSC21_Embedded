# Decision log

Why each change happened, newest first. One entry per change or decision, including
ideas we dropped. Status lines get updated in place; a reversed decision gets a new entry
that links back. Entries dated before 14 Nov 2026 were backfilled on 14 Nov from the chat
where they were decided and the commits that built them.

## 2026-11-16 · Live room: readings strip above the map, no blank under it
- **From → to:** the map sat on the left with one tall column on the right (alerts, Loudness, Air and Comfort, What happened). Now Loudness, Air and Comfort sit in a strip above the map, and the right column (alerts, area details, What happened) runs beside both and ends level with the map. What happened lists up to 12 recent events on wide screens, scrolling inside the card if needed, and 4 when it stacks under the map.
- **Why:** ZhiHao flagged the empty space on a full-screen browser and picked option A from a mockup of three layouts (chat, 16 Nov).
- **Problem it solves:** the map keeps its floor-plan shape, so its height follows its width; the right column was about twice as tall, which left a large blank area under the map at 1920 px.
- **Why this way:** three columns (map, readings, events) lost because the readings column still ran taller in some states. Stretching the map lost because the floor plan has a fixed shape, so the blank space would only move inside the panel.
- **Risks to watch:** at 901–1180 px Loudness takes its own row, so the map starts lower on laptops. Many alerts at once can make the right column taller than the map again.
- **Verified:** in the browser with the demo simulator at 1920, 1600, 1000 and 375 px wide: the map and right column end on the same line at the three wide sizes, no sideways scroll, no console errors; presentation mode drops the empty right column and the map takes the full width; dashboard tests pass (23). Not checked with alerts showing on a wide screen.
- **Status:** built, not committed.

## 2026-11-16 · PC side speaks MQTT: gateway, dashboard and simulator
- **From → to:** the PC side only spoke UDP. Now `pc/mosaic/mqtt.py` is a small MQTT 3.1.1 client (standard library only) plus an MQTT transport for the gateway, and `--mqtt HOST[:PORT]` on the gateway, dashboard and simulator switches to the broker. UDP stays the default for the existing firmware and tests. In MQTT mode each simulated node is its own client with its own last will, like a real node.
- **Why:** ZhiHao asked to start the PC side of the MQTT design (chat, 16 Nov).
- **Problem it solves:** the micro T-Kernel node can only reach the PC through a broker; without this the PC couldn't receive it, and nothing could be rehearsed before the node side exists.
- **Why this way:** the gateway's per-node logic, fusion, CSV, events, dashboard and evaluator are untouched; only the link under `GatewayServer` became pluggable (`UdpTransport`, `MqttTransport`). PINGs travel on the `config` topic without being retained, so the design's three topics stay as agreed. A packet whose header node ID differs from its topic is dropped. The node's last will is shown and logged (`link` events) but doesn't change ONLINE/STALE/OFFLINE, which still comes from the node's own reports, so both transports behave the same. No QoS 2, TLS or passwords: not needed on the demo hotspot.
- **Risks to watch:** if the broker stops, telemetry sent meanwhile is lost (QoS 0 by design) and shows as loss in the evaluator. Mosquitto 2 only listens on the local computer by default (seen with 2.1.2), so real nodes need a config file (README). PING times now include two broker hops. The node side still waits on the instructor about extending `mqtt_utk.c`.
- **Verified:** 14 new tests (packet bytes against the MQTT 3.1.1 layout, partial reads, topics, QoS 1 acknowledgement and resend, retained delivery, last will on a dropped link but not on a clean disconnect, keep-alive and a silent broker, refused login, gateway telemetry/CONFIG/ACK/PING over MQTT, a node publishing for another node, broker restart, simulated nodes end to end), 5 runs in a row; 290 tests pass. Ran `python -m mosaic.dashboard --mqtt … --scenario lecture` against the test broker: 4 nodes online, a CONFIG from the dashboard API applied by ACK in 76 ms, and the evaluator read the capture (79 packets, 0 lost). Against real Mosquitto 2.1.2 (Homebrew, a separate broker on port 18883): 16 of 16 checks passed (QoS 1 acknowledgement, retained CONFIG, last will on a dropped link and none after a clean disconnect, keep-alive, gateway TELEMETRY/CONFIG/ACK/PING with a 0.3 ms round trip, the node-ID guard, 3 simulated nodes with 0 lost). The dashboard's lecture scenario through Mosquitto with the broker stopped for about 6 s mid-run: 4 of 4 nodes online, 0 during the outage, 4 of 4 again within 10 s of the restart with no manual step; the evaluator counted the 22 reports sent during the outage as missing (14.6 %), and a CONFIG after the restart was applied by ACK. Not run with a real node.
- **Status:** built, not committed; branch `feat/mqtt-gateway` (from `docs/mqtt-ownership`, PR #31).

## 2026-11-16 · Node talks to the PC over MQTT; everyone keeps their original area
- **From → to:** the node sent protocol v2 over UDP straight to the PC gateway, which tracked loss, RTT and CONFIG ACKs per datagram. Now node↔PC traffic goes over MQTT, through the lwIP MQTT client the course template already ships (`node/lib/liblwip/sysdepend/pico_rp2040/mqtt_utk.c`). Subsystem owners stay as they were: Moe audio capture and DSP, Darius the int8 classifier, Kendrick the environment sensors, Arif networking and node health, ZhiHao node config and telemetry (plus the PC side). The folders are in `node/TEAM.md`.
- **Why:** ZhiHao decided both (chat, 16 Nov).
- **Problem it solves:** the template forbids application tasks from calling lwIP, so sending our UDP datagrams needed a new hook in the template's Wi-Fi task, which needed the instructor's OK. MQTT is the networking path the template already supports. Keeping the original areas means each person's tribunal work stays theirs.
- **Why this way:** the UDP hook was dropped: it changes shared template code for a transport the template doesn't offer. New owners per folder were not considered; the areas match the roles in the brief.
- **Risks to watch:** the template's MQTT client is a demo (it publishes `"hb N"` heartbeats on one topic, QoS 0, and prints what comes back), so carrying telemetry and CONFIG still means extending that file or adding our own beside it, and it has to stay inside the Wi-Fi task. The PC side needs a broker and an MQTT client, but its Python is standard-library only. The gateway's loss, RTT and CONFIG-ACK tracking and the evaluator are built around UDP datagrams. Round-trip times now pass through the broker, so the evaluator must report them as node↔broker↔PC, not network latency.
- **MQTT design (ZhiHao picked it from options, chat, 16 Nov):**
  - **Broker:** Mosquitto on the demo laptop. A broker written in Python (too risky to build now) and a cloud broker (needs internet; campus Wi-Fi may block it) lost.
  - **PC client:** a small MQTT 3.1.1 client in standard-library Python (connect, subscribe, publish, keep-alive), so the PC side stays standard-library only. `paho-mqtt` lost: every laptop would need `pip install`.
  - **Payload:** protocol v2 bytes unchanged inside each message, so packing, decoding, the C/Python cross-check, sequence numbers, loss stats and the evaluator keep working. JSON lost: it rewrites both ends.
  - **Topics:** `mosaic/node/<id>/telemetry` (node to PC); `mosaic/node/<id>/config` (PC to node, retained, so a rebooted node gets its config back); `mosaic/node/<id>/status` as the MQTT last will (online/offline).
  - **Delivery:** telemetry at QoS 0, since our sequence numbers already count losses; CONFIG at QoS 1, and our own CONFIG_ACK stays, because MQTT's acknowledgement only proves the broker got it.
  - **Node side:** telemetry and CONFIG go through the template's MQTT code in the Wi-Fi task, which means extending `mqtt_utk.c` (shared template code), so the instructor is asked first.
- **Verified:** read `mqtt_utk.c`/`.h`; built the template's `NET=lwip MQTT=1` image locally (Pico SDK 2.3.0, GCC 15.2): 0 warnings, 330.7 KB flash, 80.4 KB static RAM. Not run against a broker; not on a Pico.
- **Status:** decided; nothing built yet. Waiting on the instructor about extending `mqtt_utk.c`.

## 2026-11-16 · CI builds `node/`, and the budget tool reads the template build
- **From → to:** CI built only the CMake firmware in `firmware/`, and `fw_budget.py` only understood the Pico SDK's build. Now a CI job builds the template node in `node/` (the self-test, `NET=lwip` and default images, Pico SDK 2.2.0, Arm GCC 15.2) and attaches the budget report; the tool reads TRON's linker symbols, finds images in `build_make/`, and counts only `node/app_program/` as our code.
- **Why:** ZhiHao asked to carry on with work that doesn't wait on the team (chat, 16 Nov). Every PR that moves code into `node/` should prove it still builds, and the flash/RAM evidence has to come from the micro T-Kernel node now.
- **Problem it solves:** nothing checked that `node/` compiles. The budget tool crashed on the template's ELF (no `__flash_binary_end`) and would have counted the kernel as our code.
- **Why this way:** SDK 2.2.0 is what the template's README tells teammates to install; 2.3.0 was already checked locally, so CI covers the other version. Only the three SDK submodules the template uses are fetched. The default image builds last so the object files on disk match it for the float check. The step can't fail the build, like the existing budget step.
- **Risks to watch:** SDK 2.2.0 is only built in CI, not on this Mac. The float check reads the object files of the last build, so for the self-test and lwIP images it reflects the default build's objects.
- **Verified:** ran the CI job's exact commands on a clean copy of the branch (SDK 2.3.0, GCC 15.2): all three images built and the report came out (default 278.7 KB flash / 24.0 KB static RAM; lwIP 321.3 / 80.2; self-test 280.9 / 24.0), matching `arm-none-eabi-size` by hand. 4 new tests for the template layout; the CMake report is unchanged. In CI (SDK 2.2.0), every step of the "Build node" job passed and the report matched the local figures to within 0.1 KB (default flash 278.6 KB).
- **Status:** merged in PR #30 (`49e3ce1`).

## 2026-11-16 · Course template comes in as a git subtree at `node/`
- **From → to:** the template only lived in the fork `yuzhihao1212/INF2004_micro-t-kernel`. Now it comes into this repo as a git subtree at `node/`, pulled from the instructor's `sirfonzie/INF2004_ProjectTemplate` (commit `c3b0954`, the same as the fork) with its history. `firmware/` stays as it is for now.
- **Why:** ZhiHao chose it (chat, 16 Nov) after confirming the hand-in is this repo.
- **Problem it solves:** the node firmware has to be in the repo we hand in, next to the PC code, docs and evidence, without losing the instructor's later fixes to the template.
- **Why this way:** a plain copy can't easily take the instructor's fixes later. A submodule needs extra git commands from every teammate and often goes wrong on Windows. Making the fork the firmware repo was dropped because the hand-in is this repo. Pulling from `sirfonzie`, not the fork, means template fixes come straight from the instructor (`git subtree pull --prefix=node https://github.com/sirfonzie/INF2004_ProjectTemplate.git main`). History is kept (no `--squash`) so git shows the template's code as the instructor's, not ours. `node/` doesn't collide with `firmware/`.
- **Risks to watch:** editing the template's shared code under `node/` (kernel, libraries, drivers, makefiles) makes later subtree pulls conflict, so changes there need the team and the instructor to agree. Two builds live side by side for now (CMake in `firmware/`, `make` in `node/build_make/`), and CI doesn't build `node/` yet. The template wants Pico SDK 2.2.0 or 2.3.0; the existing CI uses 1.5.1 for `firmware/`.
- **Verified:** built the template from a scratch clone on ZhiHao's Mac with Pico SDK 2.3.0 and Arm GCC 15.2: the default, `NET=lwip` and `TEST=1` images, 0 warnings. `git subtree` is available (Apple Git 2.39.5). After the import: `node/` has the same git tree as the instructor's `c3b0954` (`7e925c2`), and the default image builds from the committed files with 0 warnings. Not run on a Pico; not built in CI.
- **Status:** merged in PR #30 (`49e3ce1`; subtree merge `af1c55d`).

## 2026-11-16 · μT-Kernel 3.0 is a hard requirement; the course template already has the port
- **From → to:** the node ran FreeRTOS (`mosaic_node_rtos`, PR #18, checked on hardware on 9 Nov), and a from-scratch single-core μT-Kernel port had been started in `firmware/utk/` (branch `feat/utkernel-port`, not committed). Now μT-Kernel 3.0 is fixed as the node RTOS, and `AGENTS.md` (which Claude also reads through `CLAUDE.md`) says so, so assistants stop suggesting FreeRTOS.
- **Why:** ZhiHao confirmed in chat (16 Nov) that μT-Kernel is a hard requirement, and forked the course template `sirfonzie/INF2004_ProjectTemplate` as `yuzhihao1212/INF2004_micro-t-kernel`. The revised brief (14 Sep) only says "an RTOS", so the written source of the requirement still needs linking here.
- **Problem it solves:** earlier the same day, Claude advised keeping the demo node on FreeRTOS and running the port as a side project, and wrongly said no ready-made Pico port existed. Both are withdrawn: the template already runs μT-Kernel 3.0 on both cores with the USB console, Wi-Fi, lwIP and MQTT, and its README says it's derived from TRON's `mtk3_bsp` `pico_rp2040` branch.
- **Why this way:** a rule file in the repo reaches every Claude and Codex session, teammates' included; a personal memory note would reach one computer.
- **Risks to watch:** the template forbids application tasks from calling lwIP or `cyw43_*`, but our node sends UDP from its own task; moving that into `cyw43_utk_task` needs the instructor's OK. It builds with `make` against Pico SDK 2.2.0 (we use CMake and 1.5.1, and Windows needs WSL) and compiles only `dma.c`, `gpio.c` and `pio.c` from the SDK, so our ADC, UART and watchdog code needs rework. Still open: which folder the subtree lands in, and who moves which task into which `subsystemN/`. The SDK's PIO/DMA/GPIO headers are only on the Wi-Fi driver's include path, so subsystem code that uses them (DHT22 PIO, mic DMA) needs that path added to the application's flags.
- **Own port dropped (16 Nov):** ZhiHao chose the template over the `firmware/utk/` port. That port had compiled cleanly with SDK 2.3.0 (kernel v3.00.08, a bring-up image and a `mosaic_node_utk` node) but never ran on a Pico, and it was single-core. It stays uncommitted in the `.claude/worktrees/utk-port` worktree for reference until the move is done, then gets deleted.
- **Hand-in stays in this repo (16 Nov):** ZhiHao confirmed the hand-in doesn't have to be the template fork, so the template's code comes into this repo, keeping our CI, branch protection, PR reviews and the PC, ML and docs folders in one place. ZhiHao chose a git subtree (16 Nov, decided in another session) over a plain copy, which loses the link to the template's commits, and a submodule, which would split every node change across two repos. The target folder gets recorded with the move.
- **Verified:** read the template's README, `TEAM.md`, `testing/README.md` and makefile through `gh`, and the `firmware/utk/` files. Not verified: that the template builds or runs here.
- **Status:** rule files merged in PR #29 (`f336ebd`). Template location, owners and the node↔PC transport are decided (see the entries above).

## 2026-11-16 · Evaluator measures CONFIG round trips
- **From → to:** the evaluator counted CONFIG outcomes per node but timed nothing. Now each report has a "CONFIG round trip" section: request → applied (what the operator waits for) and last send → ACK (one network round trip), with outcomes and how each was confirmed. The gateway's `applied` event now says `via: ack` or `via: telemetry`.
- **Why:** second item ZhiHao picked from the evidence plan (chat, 16 Nov). The brief asks for configuration sent back to the nodes, and a measured round trip is stronger evidence than "it works".
- **Problem it solves:** without `via`, a CONFIG whose ACK was lost (confirmed later by TELEMETRY) would look like a 1-second "round trip" and skew the numbers.
- **Why this way:** two measures rather than one, because the operator's wait includes retries and the gateway's poll, while the ACK time is the network's share. Stale-version resends stay part of the same request. Fixing the poll delay (below) was left out: it's a separate gateway change.
- **Risks to watch:** a scripted run showed the operator waits ~120 ms (p50) while the ACK takes 1–2 ms. The gap is the gateway's 200 ms `poll()` timeout before the first send. If real-node numbers look slow, that's the first thing to change (send at once from `set_config`, or wake the loop).
- **Verified:** 6 new tests (ACK after a retry, ACK lost, stale version, rejected/failed/superseded/unfinished, summary and report, old logs without `via`); 271 tests pass. Four scripted nodes, 20 CONFIGs: 20 applied, all by ACK; request → applied p50 120 ms, p95 194 ms; last send → ACK p50 1 ms. Not verified on a real Pico.
- **Status:** merged in PR #28 (`c6d30d9`). The merge of `main` into PR #29 (`634343f`) dropped this entry from `main`; PR #30 (`49e3ce1`) restored it.

## 2026-11-16 · Area card and room map get animated scenes
- **From → to:** the area card was a label/value list (Sound, Air, Temperature, Movement, each with a rainbow icon and a sentence). Now it's one big word for sound with a live sound meter, then three tiles whose effects show the state: haze that thickens as CO₂ rises, heat lines when it's warm, and footsteps for movement. The room map uses the same effects: haze and heat always show where there's a problem, footsteps only in the Movement view.
- **Why:** ZhiHao found the card looked "AI-generated", then asked for something direct and visual for non-technical users. He chose option 1 from a mockup, asked for premium animated effects, and asked for footprints after the first version looked like raindrops (chat, 16 Nov).
- **Problem it solves:** every row had the same weight, so nothing said what mattered. The wording was long, and movement showed an amber warning even in the lecturer's area, where walking is normal.
- **Why this way:** traffic-light gauges (option 2) and a "Now · Why · Next" card with a timeline and CO₂ forecast were dropped: the gauges read as technical, the long card was wordy, and a wrong forecast during the demo would look worse than none. Filling "glass" tiles were dropped because a full glass reads as good. All effects are CSS on elements built once, so the 1 s refresh never restarts an animation; there are no new libraries.
- **Also:** movement is now information, never a warning (`feedback.py`: its level is "fine" whenever there's a reading). Footprints are bare feet with toes, the shape people read as footsteps; the first shoe-print version looked like drops.
- **Risks to watch:** constant motion on the projector could distract; effects are low-opacity and scale with the problem, so calm areas barely move. This is dashboard work after the evidence plan said the UI stops; kept small (front end plus one line of Python).
- **Verified:** in the browser at 1280 and 800 wide and on a 375 px phone, light and dark, 3D and flat; effects checked at full strength by forcing them, then on live demo data (lecturer speaking, air getting stuffy, some movement); card focus goes to Close; no console errors; 265 tests pass. Not verified: the reduced-motion fallback (written, but the browser here can't emulate the setting).
- **Status:** merged in PR #27 (`3d5d5dd`).

## 2026-11-16 · Firmware flash/RAM budget and float check, run by CI
- **From → to:** no measured memory figures and no build-level float check (the tracker row said "to do"). Now `firmware/tools/fw_budget.py` reports flash, RAM, what fills them, and every float call in our code by function; CI runs it on every PR and puts the report on the run's summary page. First results are in `docs/resource_budget.md`.
- **Why:** first item ZhiHao picked from the evidence plan (chat, 16 Nov): it needs no Pico or teammate, and the brief asks for the no-floats evidence directly.
- **Problem it solves:** the CSC21 claim "no floats in the processing path" rested on reading the source. The build now shows it: node, classifier and the per-window DSP have none; `audio_dsp_init` uses float maths once at start-up to build integer tables.
- **Why this way:** plain `arm-none-eabi-size` gives section totals but not who uses the RAM or where floats come from. The script reads the linker map and object files instead. Running it in CI gives numbers from the team's SDK 1.5.1 build with no extra setup. Changing the DSP tables to `const` and shrinking lwIP's 36 KB packet pool were left to Moe and Arif, since those are their parts.
- **Fix after the first CI run (16 Nov):** CI's SDK 1.5.1 report showed 2 KB of heap and no breakdown. In 1.5.1 `__HeapLimit` only marks a 2 KB placeholder (the heap really grows to `__StackLimit`), and the map can be named `<name>.map`. Both fixed; the same report showed the RTOS node at 121.7 KB static RAM, so the node-plus-audio estimate went from 138 KB to about 200 KB of 256 KB.
- **Risks to watch:** the local figures come from SDK 2.3.0/GCC 15.2 and may differ by a few KB from CI's; use CI's in the write-up. The CI step can't fail the build (`continue-on-error`), so check that its summary appears. The ~200 KB node-plus-audio RAM figure is an estimate until audio is linked.
- **Verified:** built `mosaic_node`, `audio_talking` and `audio_benchmark` locally and ran the script; flash and RAM totals match the linker symbols by hand; float calls confirmed with `objdump`. 4 new parser tests; 265 tests pass. Not verified: the CI step itself (runs on the next push) and the RTOS build (FreeRTOS isn't installed locally).
- **Status:** merged in PR #26 (`fc58a5d`; SDK 1.5.1 fix `ca55a21`).

## 2026-11-16 · Week 13 evidence plan: the node gets measured, the UI stops
- **From → to:** no plan for the node-side evidence; the CSC21 tracker listed what was missing but not who does it or how. Now `docs/evidence_plan_week13.md` lists each item with an owner, a method and a "done when", and dashboard work stops.
- **Why:** ZhiHao asked for an honest rating and what would lift the project to A+ (chat, 16 Nov). The estimate was about 70/100: the PC side is strong, but audio isn't on the node and none of the 21 Week 10 hardware tests has a result.
- **Problem it solves:** an embedded project is judged on the node. Without measured timing, memory, accuracy and reliability numbers, the brief's Week 13 evidence can't be shown.
- **Why this way:** taking over teammates' parts was considered and dropped: tribunals mark each person on their own work. Instead ZhiHao pairs on the audio hookup (ZhiHao co-owns the protocol and node config) and takes the system-evaluation items already in his role. Reassignment only happens if the team agrees it in writing after a missed date.
- **Risks to watch:** the plan runs into Week 12, which was meant to be free for individual assessments. Dates are proposals until the team agrees them. If audio misses its date, the fallback is the Week 10 plan's: demo sensors, CONFIG and recovery on real nodes, audio from the simulator, and say so openly.
- **Verified:** read in the repo on 16 Nov: the tracker, the Week 10 test plan (results blank), `MOSAIC_NODE_AUDIO_SOURCES` empty, and the RTOS build already printing watchdog reset reason and heap/stack high-water marks every 10 s. CPU load isn't measured anywhere. The ~70/100 is an estimate; the brief has no rubric.
- **Status:** proposed; the plan document merged in PR #25 (`535f2e9`). Still needs the team's OK in the group chat.

## 2026-11-16 · Room map gets a 3D view (isometric diorama)
- **From → to:** the Live room map was a flat floor plan. Now a Flat / 3D switch tilts it into an isometric diorama: far walls, whiteboard and desks are extruded, rings lie on the floor, and labels float upright above each area. 3D is the default; phones stay flat.
- **Why:** ZhiHao asked whether the classroom could look like a premium 3D illustration for demo day, and picked option A from a mockup (chat, 16 Nov).
- **Problem it solves:** the flat plan was clear but plain; the 3D view makes the room read as a real space at a glance on the projector.
- **Why this way:** B (a slowly orbiting camera you can drag) was dropped: nobody drags on a projector, and constant motion pulls the eye from the area that turns red. A 3D engine (Three.js) was dropped: a large library to bundle, and the map would become one picture screen readers can't use. A hand-made Blender illustration was dropped: it breaks when the zone layout changes. CSS transforms on the existing plan keep the zone layout, the buttons and the labels as they are.
- **Risks to watch:** a slow laptop may render the 3D boxes less smoothly; the Flat switch is the fallback. The label layer is re-positioned on each refresh, so a label could lag a resize for a moment.
- **Verified:** in the browser: dark and light, the tilt animation, clicks land on the right tilted area, Flat/3D is remembered, 375 px stays flat with the switch hidden, 1366 × 768, and 1920 × 1080 in presenter mode with the map fully on screen; no console errors; 261 tests pass.
- **Status:** merged in PR #25 (`d8f760e`).

## 2026-11-16 · "Live room" page replaces Overview and Room map
- **From → to:** five pages, with the room map below the fold on Overview and again on its own page, and a side rail. Now: one projector-first "Live room" page with the animated map in the middle, a plain-language headline, an alert card with one action, loudness/air/comfort cards, a last-10-minutes bar and a presenter mode (P). Four pages in all: Live room, History, Sensors, Setup, under one top bar. Dark theme is a deeper ink; light keeps today's colours.
- **Why:** ZhiHao wanted a high-end upgrade designed from the lecturer's side for demo day, and picked direction A ("Live room") from two clickable prototypes (chat, 16 Nov). ZhiHao then chose to build it in this Claude session instead of handing it to Codex.
- **Problem it solves:** at 1366 × 768 the Overview repeated its headline in the Sound card and hid the map below the fold. The simulation strip only showed on Room map, so an assessor on Overview couldn't tell which phase was playing.
- **Why this way:** B ("Calm glance", big sentence and ring gauges) read well from the back of a room but hid where things happen; its presenter mode is kept. Decibels and head counts were dropped because the node sends uncalibrated RMS and PIR can't count people; loudness shows as "% of the area's noise limit". No JS framework or build step, so the page stays standard library. The lecturer's voice is blue, not the prototype's lavender, because purple means "clickable" in the colour rules; area colours are a new fifth family in CONTRIBUTING.md. The Air card shows the server's verdict, not its own, after a test showed "Stuffy" on the card beside "The air is fresh" in the headline.
- **Font:** Plus Jakarta Sans (SIL OFL 1.1) replaces Poppins and is self-hosted: two variable woff2 files (latin and latin-ext, 49 KB) and the licence sit directly in `pc/mosaic/web/`, and the server now sends `.woff2` (ZhiHao approved the download, chat, 16 Nov). They sit in `web/` itself rather than a `fonts/` folder so the "files directly inside web/ only" rule against path tricks stays as it is. Before this, both the old and new font came from Google Fonts and fell back to the system font with no internet.
- **Risks to watch:** the feature freeze was end of Week 11, and audio on the node is the bigger demo risk. Dark colours can wash out on a projector, so both themes stay. The new colour family needs the team's OK (CONTRIBUTING asks for that).
- **Verified:** 261 tests pass. In the browser with a sped-up demo scenario: lecture, talking, excessive noise with the alert card, CO₂ haze, window opened and air-conditioning phases; area details open and close (Escape returns focus); presenter mode; light and dark; 375 px, 1366 × 768 and 1920 × 1080 with no sideways scroll; History, Sensors and Setup; no console errors. After self-hosting: the font loads from localhost, the page makes no requests outside localhost, and the top bar fits one line at 1024 px. Not checked: reduced motion (the CSS rule is in place but wasn't emulated), a real projector, real nodes.
- **Status:** merged in PR #25 (`d8f760e`).

## 2026-11-14 · Noise-limit target stays at 70 dB for now
- **From → to:** no change. The Setup dialog still asks for 70 dB; a switch to 65 dB was considered and not made.
- **Why:** ZhiHao kept 70 (chat, 14 Nov) because only one source has been opened and confirmed.
- **Problem it solves:** avoids citing figures we haven't read, as the project's research rules require.
- **Why this way:** a literature search suggested 65 dB, the top of measured occupied lessons (about 55–65 dB LAeq; one survey mean 64.2). Only WHO 1999 was verified, and it gives 35 dB LAeq during teaching, a background goal rather than an activity level. The other figures came from search summaries and stay "to verify".
- **Risks to watch:** 70 dB may flag too rarely in a real room. The studies average over minutes while our check uses 10 s, so the report needs to state that difference. Revisit once the occupied-classroom survey is opened, or after the first real-room capture.
- **Verified:** WHO text read. Everything else is unverified.
- **Status:** decided; logged in PR #23 (`55def5f`). `TARGET_DB` in `app.js` and the docs still say placeholder.

## 2026-11-14 · CSC21 tracker and fault table brought up to date
- **From → to:** the tracker listed fusion's numeric table and the integer-vs-float fusion comparison as "To do", and fault F5 as "In progress". Now: both tracker rows are done, the PC half of the no-floats check is recorded, and F5 is ✅.
- **Why:** a progress check before Week 13 (ZhiHao, in chat) found these rows were stale and made the project look further behind than it is.
- **Problem it solves:** the tracker is the Week 13 evidence list, so stale rows would hide work that's already done.
- **Why this way:** the rows were updated in place and point at the existing evidence. No new document was written.
- **Risks to watch:** the fusion comparison uses simulated scenarios only. If real-room data disagrees, the row needs a real-data comparison.
- **Verified:** reran `test_integer_accuracy.py` and `test_integer_enforcement.py` on 14 Nov. Same state sequence; 93 activity transitions at most 500 ms apart; the allow-list holds `seconds_to_ms` only.
- **Status:** merged in PR #23 (`fb51677`).

## 2026-11-13 · Loss tooltip moved onto the new Sensors row
- **From → to:** `main` (Kendrick) added a loss explanation to the old Sensors card. The redesigned page has no cards, so the explanation now shows on hover over each row's link line.
- **Why:** this resolved the merge conflict when bringing `main` into `feat/friendly-ui` (ZhiHao, in chat).
- **Why this way:** keeping the old cards would undo the simpler page, and dropping the tooltip would lose Kendrick's distinction between unrecovered loss and recovered loss.
- **Risks to watch:** a hover title doesn't work on touch screens or for keyboard users. If assessors use a tablet, show it as text instead.
- **Verified:** 261 tests passed. In the browser, all 4 rows showed the hover text with the new fields and the console had no errors.
- **Status:** merged in PR #22 (`678addd`).

## 2026-11-13 · Noise limit set through a guided dialog with a live meter
- **From → to:** there was no way to set the excessive-noise level. Now Setup › Noise limit walks through each area: make the sound, watch the meter, Capture, then Next.
- **Why:** ZhiHao picked option B from three mockups (chat, 13 Nov).
- **Why this way:** A (a Set button per area) was quicker, but nothing showed whether the sensor actually heard the sound. C (set it on the Sensors page) would split setup across two pages.
- **Risks to watch:** the 70 dB target is a placeholder until it has a source. The meter's ceiling warning assumes AC RMS from a 12-bit ADC tops out near 2048 counts, which hasn't been measured on a node.
- **Verified:** in the browser, at phone and desktop widths, light and dark: capture, countdown, saved, skip, done and Remove all all worked.
- **Status:** merged in PR #22 (`e79a7bb`).

## 2026-11-12 · "Excessive noise" defined as a sound-meter level per area
- **From → to:** any noisy student area showed "Talking". Now an area above its captured limit (70% of windows over 10 s, then the 10 s zone wait) shows "Excessive noise" (`LOUD`). It's Act now in Lecture and Quiet work, and a heads-up in Group work.
- **Why:** ZhiHao wanted a threshold rather than just "got noise" (chat, 12 Nov), and picked option A.
- **Why this way:** a limit relative to voice calibration was dropped, because calibration learns lecturer-voice bleed, not loudness. B (a learned quiet baseline plus a jump) drifts, and never flags a room that's loud from the start. Excessive noise is a zone state only; no new classroom state, so the statechart stays as reviewed.
- **Risks to watch:** the node reports unweighted RMS, not dB(A). Phone meters are ±2–3 dB. The lecturer's area is never checked.
- **Verified:** 242 tests at the time, including that no scenario goes `LOUD` outside the rowdy phase. The capture API worked on the live dashboard.
- **Status:** merged in PR #22 (`e79a7bb`, docs `cec0207`).

## 2026-11-11 · Dashboard redesign: logo, side rail, colour rules, intro, Sensors table, simulation strip
- **From → to:** red-themed top bar, cards per sensor, no scenario context. Now: a four-shard animated logo, a side rail with a purple accent, one colour system with dot tags, an intro that flies the logo into the rail, one table row per sensor, and a strip above the Room map naming the simulated phase.
- **Why:** ZhiHao asked for a cleaner, consistent look and picked from mockups each time: logo B2, colour direction 3 with dot tags, intro A, Sensors A, strip A (chat, 11 Nov).
- **Why this way:** a red theme clashed with the multicolour logo. Per-tag colours were too many, so colour now means only one of: clickable, health status or sensor type. The cards repeated detail the lecturer doesn't need.
- **Risks to watch:** the intro must never block the page. It ends after 8 s at most, and right away in a background tab.
- **Verified:** viewed in the browser at phone and desktop widths, light and dark. The logo's landing position was measured within 1 px.
- **Status:** merged in PR #22 (`820fb52`, `ebd52a6`, `8fac080`, `f8aabec`, `2d6b2e4`). The colour rules are in CONTRIBUTING.md.
