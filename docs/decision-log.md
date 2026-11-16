# Decision log

Why each change happened, newest first. One entry per change or decision, including
ideas we dropped. Status lines get updated in place; a reversed decision gets a new entry
that links back. Entries dated before 14 Nov 2026 were backfilled on 14 Nov from the chat
where they were decided and the commits that built them.

## 2026-11-16 · μT-Kernel 3.0 is a hard requirement; the course template already has the port
- **From → to:** the node ran FreeRTOS (`mosaic_node_rtos`, PR #18, checked on hardware on 9 Nov), and a from-scratch single-core μT-Kernel port had been started in `firmware/utk/` (branch `feat/utkernel-port`, not committed). Now μT-Kernel 3.0 is fixed as the node RTOS, and `AGENTS.md` (which Claude also reads through `CLAUDE.md`) says so, so assistants stop suggesting FreeRTOS.
- **Why:** ZhiHao confirmed in chat (16 Nov) that μT-Kernel is a hard requirement, and forked the course template `sirfonzie/INF2004_ProjectTemplate` as `yuzhihao1212/INF2004_micro-t-kernel`. The revised brief (14 Sep) only says "an RTOS", so the written source of the requirement still needs linking here.
- **Problem it solves:** earlier the same day, Claude advised keeping the demo node on FreeRTOS and running the port as a side project, and wrongly said no ready-made Pico port existed. Both are withdrawn: the template already runs μT-Kernel 3.0 on both cores with the USB console, Wi-Fi, lwIP and MQTT, and its README says it's derived from TRON's `mtk3_bsp` `pico_rp2040` branch.
- **Why this way:** a rule file in the repo reaches every Claude and Codex session, teammates' included; a personal memory note would reach one computer.
- **Risks to watch:** the template forbids application tasks from calling lwIP or `cyw43_*`, but our node sends UDP from its own task; moving that into `cyw43_utk_task` needs the instructor's OK. It builds with `make` against Pico SDK 2.2.0 (we use CMake and 1.5.1, and Windows needs WSL) and compiles only `dma.c`, `gpio.c` and `pio.c` from the SDK, so our ADC, UART and watchdog code needs rework. Still open: where the template sits relative to this repo, whether `firmware/utk/` is dropped, and who moves which task into which `subsystemN/`.
- **Verified:** read the template's README, `TEAM.md`, `testing/README.md` and makefile through `gh`, and the `firmware/utk/` files. Not verified: that the template builds or runs here.
- **Status:** rule files and this entry built, not committed; the open decisions above are pending.

## 2026-11-16 · Area card and room map get animated scenes
- **From → to:** the area card was a label/value list (Sound, Air, Temperature, Movement, each with a rainbow icon and a sentence). Now it's one big word for sound with a live sound meter, then three tiles whose effects show the state: haze that thickens as CO₂ rises, heat lines when it's warm, and footsteps for movement. The room map uses the same effects: haze and heat always show where there's a problem, footsteps only in the Movement view.
- **Why:** ZhiHao found the card looked "AI-generated", then asked for something direct and visual for non-technical users. He chose option 1 from a mockup, asked for premium animated effects, and asked for footprints after the first version looked like raindrops (chat, 16 Nov).
- **Problem it solves:** every row had the same weight, so nothing said what mattered. The wording was long, and movement showed an amber warning even in the lecturer's area, where walking is normal.
- **Why this way:** traffic-light gauges (option 2) and a "Now · Why · Next" card with a timeline and CO₂ forecast were dropped: the gauges read as technical, the long card was wordy, and a wrong forecast during the demo would look worse than none. Filling "glass" tiles were dropped because a full glass reads as good. All effects are CSS on elements built once, so the 1 s refresh never restarts an animation; there are no new libraries.
- **Also:** movement is now information, never a warning (`feedback.py`: its level is "fine" whenever there's a reading). Footprints are bare feet with toes, the shape people read as footsteps; the first shoe-print version looked like drops.
- **Risks to watch:** constant motion on the projector could distract; effects are low-opacity and scale with the problem, so calm areas barely move. This is dashboard work after the evidence plan said the UI stops; kept small (front end plus one line of Python).
- **Verified:** in the browser at 1280 and 800 wide and on a 375 px phone, light and dark, 3D and flat; effects checked at full strength by forcing them, then on live demo data (lecturer speaking, air getting stuffy, some movement); card focus goes to Close; no console errors; 265 tests pass. Not verified: the reduced-motion fallback (written, but the browser here can't emulate the setting).
- **Status:** built, not committed; branch `feat/live-room-ui` (PR #25).

## 2026-11-16 · Firmware flash/RAM budget and float check, run by CI
- **From → to:** no measured memory figures and no build-level float check (the tracker row said "to do"). Now `firmware/tools/fw_budget.py` reports flash, RAM, what fills them, and every float call in our code by function; CI runs it on every PR and puts the report on the run's summary page. First results are in `docs/resource_budget.md`.
- **Why:** first item ZhiHao picked from the evidence plan (chat, 16 Nov): it needs no Pico or teammate, and the brief asks for the no-floats evidence directly.
- **Problem it solves:** the CSC21 claim "no floats in the processing path" rested on reading the source. The build now shows it: node, classifier and the per-window DSP have none; `audio_dsp_init` uses float maths once at start-up to build integer tables.
- **Why this way:** plain `arm-none-eabi-size` gives section totals but not who uses the RAM or where floats come from. The script reads the linker map and object files instead. Running it in CI gives numbers from the team's SDK 1.5.1 build with no extra setup. Changing the DSP tables to `const` and shrinking lwIP's 36 KB packet pool were left to Moe and Arif, since those are their parts.
- **Fix after the first CI run (16 Nov):** CI's SDK 1.5.1 report showed 2 KB of heap and no breakdown. In 1.5.1 `__HeapLimit` only marks a 2 KB placeholder (the heap really grows to `__StackLimit`), and the map can be named `<name>.map`. Both fixed; the same report showed the RTOS node at 121.7 KB static RAM, so the node-plus-audio estimate went from 138 KB to about 200 KB of 256 KB.
- **Risks to watch:** the local figures come from SDK 2.3.0/GCC 15.2 and may differ by a few KB from CI's; use CI's in the write-up. The CI step can't fail the build (`continue-on-error`), so check that its summary appears. The ~200 KB node-plus-audio RAM figure is an estimate until audio is linked.
- **Verified:** built `mosaic_node`, `audio_talking` and `audio_benchmark` locally and ran the script; flash and RAM totals match the linker symbols by hand; float calls confirmed with `objdump`. 4 new parser tests; 265 tests pass. Not verified: the CI step itself (runs on the next push) and the RTOS build (FreeRTOS isn't installed locally).
- **Status:** built, not committed; branch `feat/firmware-budget` (from `feat/live-room-ui`).

## 2026-11-16 · Week 13 evidence plan: the node gets measured, the UI stops
- **From → to:** no plan for the node-side evidence; the CSC21 tracker listed what was missing but not who does it or how. Now `docs/evidence_plan_week13.md` lists each item with an owner, a method and a "done when", and dashboard work stops.
- **Why:** ZhiHao asked for an honest rating and what would lift the project to A+ (chat, 16 Nov). The estimate was about 70/100: the PC side is strong, but audio isn't on the node and none of the 21 Week 10 hardware tests has a result.
- **Problem it solves:** an embedded project is judged on the node. Without measured timing, memory, accuracy and reliability numbers, the brief's Week 13 evidence can't be shown.
- **Why this way:** taking over teammates' parts was considered and dropped: tribunals mark each person on their own work. Instead ZhiHao pairs on the audio hookup (ZhiHao co-owns the protocol and node config) and takes the system-evaluation items already in his role. Reassignment only happens if the team agrees it in writing after a missed date.
- **Risks to watch:** the plan runs into Week 12, which was meant to be free for individual assessments. Dates are proposals until the team agrees them. If audio misses its date, the fallback is the Week 10 plan's: demo sensors, CONFIG and recovery on real nodes, audio from the simulator, and say so openly.
- **Verified:** read in the repo on 16 Nov: the tracker, the Week 10 test plan (results blank), `MOSAIC_NODE_AUDIO_SOURCES` empty, and the RTOS build already printing watchdog reset reason and heap/stack high-water marks every 10 s. CPU load isn't measured anywhere. The ~70/100 is an estimate; the brief has no rubric.
- **Status:** proposed; needs the team's OK in the group chat.

## 2026-11-16 · Room map gets a 3D view (isometric diorama)
- **From → to:** the Live room map was a flat floor plan. Now a Flat / 3D switch tilts it into an isometric diorama: far walls, whiteboard and desks are extruded, rings lie on the floor, and labels float upright above each area. 3D is the default; phones stay flat.
- **Why:** ZhiHao asked whether the classroom could look like a premium 3D illustration for demo day, and picked option A from a mockup (chat, 16 Nov).
- **Problem it solves:** the flat plan was clear but plain; the 3D view makes the room read as a real space at a glance on the projector.
- **Why this way:** B (a slowly orbiting camera you can drag) was dropped: nobody drags on a projector, and constant motion pulls the eye from the area that turns red. A 3D engine (Three.js) was dropped: a large library to bundle, and the map would become one picture screen readers can't use. A hand-made Blender illustration was dropped: it breaks when the zone layout changes. CSS transforms on the existing plan keep the zone layout, the buttons and the labels as they are.
- **Risks to watch:** a slow laptop may render the 3D boxes less smoothly; the Flat switch is the fallback. The label layer is re-positioned on each refresh, so a label could lag a resize for a moment.
- **Verified:** in the browser: dark and light, the tilt animation, clicks land on the right tilted area, Flat/3D is remembered, 375 px stays flat with the switch hidden, 1366 × 768, and 1920 × 1080 in presenter mode with the map fully on screen; no console errors; 261 tests pass.
- **Status:** built, not committed; branch `feat/live-room-ui`.

## 2026-11-16 · "Live room" page replaces Overview and Room map
- **From → to:** five pages, with the room map below the fold on Overview and again on its own page, and a side rail. Now: one projector-first "Live room" page with the animated map in the middle, a plain-language headline, an alert card with one action, loudness/air/comfort cards, a last-10-minutes bar and a presenter mode (P). Four pages in all: Live room, History, Sensors, Setup, under one top bar. Dark theme is a deeper ink; light keeps today's colours.
- **Why:** ZhiHao wanted a high-end upgrade designed from the lecturer's side for demo day, and picked direction A ("Live room") from two clickable prototypes (chat, 16 Nov). ZhiHao then chose to build it in this Claude session instead of handing it to Codex.
- **Problem it solves:** at 1366 × 768 the Overview repeated its headline in the Sound card and hid the map below the fold. The simulation strip only showed on Room map, so an assessor on Overview couldn't tell which phase was playing.
- **Why this way:** B ("Calm glance", big sentence and ring gauges) read well from the back of a room but hid where things happen; its presenter mode is kept. Decibels and head counts were dropped because the node sends uncalibrated RMS and PIR can't count people; loudness shows as "% of the area's noise limit". No JS framework or build step, so the page stays standard library. The lecturer's voice is blue, not the prototype's lavender, because purple means "clickable" in the colour rules; area colours are a new fifth family in CONTRIBUTING.md. The Air card shows the server's verdict, not its own, after a test showed "Stuffy" on the card beside "The air is fresh" in the headline.
- **Font:** Plus Jakarta Sans (SIL OFL 1.1) replaces Poppins and is self-hosted: two variable woff2 files (latin and latin-ext, 49 KB) and the licence sit directly in `pc/mosaic/web/`, and the server now sends `.woff2` (ZhiHao approved the download, chat, 16 Nov). They sit in `web/` itself rather than a `fonts/` folder so the "files directly inside web/ only" rule against path tricks stays as it is. Before this, both the old and new font came from Google Fonts and fell back to the system font with no internet.
- **Risks to watch:** the feature freeze was end of Week 11, and audio on the node is the bigger demo risk. Dark colours can wash out on a projector, so both themes stay. The new colour family needs the team's OK (CONTRIBUTING asks for that).
- **Verified:** 261 tests pass. In the browser with a sped-up demo scenario: lecture, talking, excessive noise with the alert card, CO₂ haze, window opened and air-conditioning phases; area details open and close (Escape returns focus); presenter mode; light and dark; 375 px, 1366 × 768 and 1920 × 1080 with no sideways scroll; History, Sensors and Setup; no console errors. After self-hosting: the font loads from localhost, the page makes no requests outside localhost, and the top bar fits one line at 1024 px. Not checked: reduced motion (the CSS rule is in place but wasn't emulated), a real projector, real nodes.
- **Status:** built, not committed; branch `feat/live-room-ui`.

## 2026-11-14 · Noise-limit target stays at 70 dB for now
- **From → to:** no change. The Setup dialog still asks for 70 dB; a switch to 65 dB was considered and not made.
- **Why:** ZhiHao kept 70 (chat, 14 Nov) because only one source has been opened and confirmed.
- **Problem it solves:** avoids citing figures we haven't read, as the project's research rules require.
- **Why this way:** a literature search suggested 65 dB, the top of measured occupied lessons (about 55–65 dB LAeq; one survey mean 64.2). Only WHO 1999 was verified, and it gives 35 dB LAeq during teaching, a background goal rather than an activity level. The other figures came from search summaries and stay "to verify".
- **Risks to watch:** 70 dB may flag too rarely in a real room. The studies average over minutes while our check uses 10 s, so the report needs to state that difference. Revisit once the occupied-classroom survey is opened, or after the first real-room capture.
- **Verified:** WHO text read. Everything else is unverified.
- **Status:** decided; `TARGET_DB` in `app.js` and the docs still say placeholder.

## 2026-11-14 · CSC21 tracker and fault table brought up to date
- **From → to:** the tracker listed fusion's numeric table and the integer-vs-float fusion comparison as "To do", and fault F5 as "In progress". Now: both tracker rows are done, the PC half of the no-floats check is recorded, and F5 is ✅.
- **Why:** a progress check before Week 13 (ZhiHao, in chat) found these rows were stale and made the project look further behind than it is.
- **Problem it solves:** the tracker is the Week 13 evidence list, so stale rows would hide work that's already done.
- **Why this way:** the rows were updated in place and point at the existing evidence. No new document was written.
- **Risks to watch:** the fusion comparison uses simulated scenarios only. If real-room data disagrees, the row needs a real-data comparison.
- **Verified:** reran `test_integer_accuracy.py` and `test_integer_enforcement.py` on 14 Nov. Same state sequence; 93 activity transitions at most 500 ms apart; the allow-list holds `seconds_to_ms` only.
- **Status:** built, not committed.

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
