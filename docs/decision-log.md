# Decision log

Why each change happened, newest first. One entry per change or decision, including
ideas we dropped. Status lines get updated in place; a reversed decision gets a new entry
that links back. Entries dated before 14 Nov 2026 were backfilled on 14 Nov from the chat
where they were decided and the commits that built them.

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
