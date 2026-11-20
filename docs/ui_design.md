# Dashboard design: plain language, HCI and accessibility

The dashboard has two audiences. A **lecturer** glances at it mid-class, often from a
distance, and needs one answer: *is the room OK, and should I do anything?* The **team or
technician** needs node health, calibration and raw readings. The design serves the
lecturer first and keeps technical detail one click away (progressive disclosure).

## Pages

The dashboard is split into four pages so each one answers one question. Navigation is
a bar of tabs across the top (a bottom bar on phones); the current page is marked with
`aria-current`, the browser title names the page, Back/Forward work (`#/live`, ...; the old
`#/overview` and `#/map` links open the Live room), and focus moves to the page heading so
screen-reader users hear where they are. *Act now* alerts sit beside the map on the Live
room and as a banner on top of every other page.

| Page | Question it answers | Contents |
|---|---|---|
| Live room | Is the room OK, where, and should I do anything? | Kicker (All good / Heads up / Act now), headline + summary, class type, simulation strip; the live floor plan (front wall with whiteboard, lecturer's desk, door, windows, desks, sensor dots) with each area's look, switchable to air, temperature or movement; beside it the alert card, Loudness, Air, Comfort and the latest 4 changes; below it the last 10 minutes as one bar. Select an area for all its readings. On narrow screens the plan turns so the front is at the top, the side column stacks under it, and the alert card moves to the top of the page so it's seen first. On screens at least 1100 × 640 the whole Live room fits one screen: a compact headline row, the map on the left filling the window's height with Last 10 minutes under it, and the readings, alert and What happened in the right column (which scrolls inside itself). The People view's camera fits the whole room into whatever space the map gets. |
| History | What happened? | Full timeline incl. cleared alerts; CO₂ and temperature charts with a text summary |
| Sensors | Is the equipment working? | A health card per node: Wi-Fi signal, last heard, messages lost and round trip, CPU load, audio work against the 500 ms window, free memory and restarts, and a 10-minute strip of half-minute stretches (green reporting, amber gaps, red silent, grey not heard yet). Below it, each node's latest readings and sound class. Simulated nodes say so once above the cards. |
| Setup | How do I change it? | Class type, voice setup (guided), noise limit (guided), report interval, technical names, theme Opens as a dialog over the current page, with the page blurred behind it (a bottom sheet on phones), so you don't leave the Live room; Esc, × or a click outside closes it, and `#/setup` links open it. |

```
┌ mosaic  ▦ Live room  ↺ History  ((•)) Sensors  ⚙ Setup      ●●●● 4/4 nodes · Simulated · ● Live  ▭ ◐ ┐
├────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ● ACT NOW                                                     Class type: (Lecture) Group work Quiet │
│ Excessive noise                                                                                      │
│ Louder than the set level in the back rows. The air is fresh.                                        │
│ [Simulated · Demo   Phase 4 of 9: Back rows get rowdy ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬            0:34 left] │
│ ┌ The room now   (Sound) Air Temperature Movement ┐  ┌ ■ Excessive noise in the back rows.          ┐ │
│ │ Lecturer's │ Front rows │ Middle rows │ Back rows│  │   Ask the class to lower the volume. [Hide]  │ │
│ │ speaking ◎ │ Settled    │ Talking ◎   │ Excessive│  ├ Loudness  177% back rows ▬▬▬▬▬▬▬▬|▬▬  ∿∿∿∿  ┤ │
│ │            │            │             │ noise ◎◎ │  ├ Air 875 ppm Fresh │ Comfort 24.0 °C Comfortab┤ │
│ └─────────────────────────────────────────────────┘  └ What happened: 10:47 … 10:44 …              ┘ │
│ [Last 10 minutes ▬▬▬▬▬▬ fine ▬▬ heads-up ▬ act now ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬ now] │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Live room: area looks

Each area on the map takes one look. With the Sound layer on, the look comes from the
zone's activity; with Air, Temperature or Movement on, it comes from that reading's level.
The word on the area is always the server's label, so colour is never the only cue.

| Zone activity | Word | Look | Rings |
|---|---|---|---|
| `LECTURER` | Lecturer speaking | blue tint (`--look-speak`) | slow blue rings, 3.3 s |
| `STILL`, `MOTION` | Settled / Moving around | faint green tint (`--look-settled`) | none |
| `TALKING` | Talking | amber tint (`--look-talk`); green in Group work, where talking is expected | amber rings, 2.4 s |
| `LOUD` | Excessive noise | red tint (`--look-loud`), border, and an inner glow that pulses every 1.8 s | fast red rings, 1.2 s |
| `NO_DATA` or sensor offline | No signal / Not connected | dashed border and diagonal hatch | none |

Each area also shows one detail line: "82% of noise limit" on the Sound layer, the
reading on the other layers, or "Last reading 30 s ago" when the sensor is offline. A
yellow haze rises inside an area as CO₂ climbs, from none at 800 ppm to strong at 1,300 ppm.

**Loudness** = the loudest student area's audio RMS against its own noise limit:
`rms × 16 / level_x16 × 100 %`, from the node's latest window and the level captured in
Setup › Noise limit. It's never shown in dB, because the microphone isn't calibrated. With
no limit set, the card links to Setup instead. The **Air** card shows the highest CO₂
reading, and which area it's from only when that area is at least 100 ppm above the next
("Similar in every area" otherwise, so the name doesn't hop around on sensor noise), with
the server's verdict for the room (so it always agrees with the headline). The **last 10 minutes** bar takes, for each stretch of time, the
worst level among the room's sound, air and comfort states and any open alert.

### Live room: 3D view

A **Flat / 3D** switch above the map tilts the same floor plan into an isometric diorama
(CSS 3D transforms, no perspective and no library). The floor, the areas and the sound
rings stay on the floor plane; the two far walls, the whiteboard, the lecturer's desk and
the student desks are extruded boxes. Labels float upright above each area in a separate
layer, so they stay readable; that layer is hidden from screen readers because the area
buttons carry the same words. The tilted areas stay real buttons. 3D is the default and
the choice is remembered in the browser; phones (and any map narrower than 560 px) always
show the flat plan. The room is scaled to fit the panel, and the switch animates the tilt
over 1.2 s.

### Live room: motion

All motion is CSS except the number count-up, and all of it turns off under
`prefers-reduced-motion` (numbers then change at once, and sparklines are drawn without
the draw-in).

| What | When | How |
|---|---|---|
| Area colour and border | Area changes look | ease over 0.9 s |
| Sound rings | While speaking, talking or too loud | three rings per area grow from 0.35× to 4.4× and fade, staggered by a third of the cycle |
| Excessive-noise glow | While an area is too loud | inner glow pulses every 1.8 s |
| CO₂ haze | As CO₂ changes | opacity eases over 1.6 s |
| Headline block | Headline text changes | rises 14 px and un-blurs over 0.7 s (not on first load) |
| Numbers on the cards | Value changes | count to the new value over 0.8 s, ease-out |
| Sparklines | First shown | draw in over 1.1 s |
| Alert card | New alert | slides down 12 px with a slight overshoot, 0.55 s |
| What happened | New row | slides in from above |
| Logo | While any act-now alert shows | the four shards spring a few pixels apart, and back after |

### Presenter mode

The screen button in the top bar, or **P** (ignored while typing or in a dialog), hides
the tabs, What happened, the last-10-minutes bar and the class type, and makes the
headline (up to 76 px), the map and the loudness number bigger. The choice is remembered
in this browser.

## Plain-language labels

The engine's names stay in code, logs and the evaluator. The screen shows the words
on the right. A **Show technical names** switch on the *Setup* page adds the
engine name in brackets, so we can map the screen to the statechart in the tribunal.

**Headline:** the label of the most urgent of sound, air and comfort, by level, so it
always matches the kicker above it ("Act now: The air is stuffy", not "Act now: Lecture in
progress"). Sound wins ties, and its sentence moves into the summary. With fewer than half
the sensors working and nothing more urgent, the headline is "Most sensors aren't working".

| Engine state | Headline / label | Summary or "why" line (example) |
|---|---|---|
| Activity `UNKNOWN` | Checking the room… | "Waiting for enough readings (about 20 s)." Not "No data" when sensors are working. |
| `EMPTY` | Room is empty | "No one has been detected for 10 minutes." |
| `QUIET` | Quiet | "People are here, no one is talking much." |
| `FOCUSED_LECTURE` | Lecture in progress | "The lecturer is speaking and students are quiet." |
| `NOISE_RISING` | Getting noisy | "Talking at the back right." |
| `SUSTAINED_CHATTER` | Ongoing chatter | "Talking at the back right for 2 minutes." |
| `DISCUSSION` | Group discussion | "Most groups are talking, as expected in group work." |
| Air `NORMAL` / `POOR_VENTILATION` / `UNKNOWN` | Fresh / Stuffy / Sensor warming up; **Clearing** while the engine still holds `POOR_VENTILATION` but every reading is already under its recovery line (`co2_recovered_ppm`, 1,000 ppm) | "Stuffiest in the back rows." only when that area is 100 ppm above the next, else "Stuffy across the room." / Clearing: "CO₂ is back down to 774 ppm. The stuffy warning ends once it stays down for about a minute." (no alert) / "Ready in about 3 minutes." |
| Comfort `COMFORTABLE` / `OUT_OF_RANGE` / `UNKNOWN` | Comfortable / Too warm, Too cold, Too humid, Too dry / No reading | Direction comes from which limit was crossed. |
| Zone `LECTURER` / `TALKING` / `LOUD` / `MOTION` / `STILL` / `NO_DATA` | Lecturer speaking / Talking / Excessive noise / Moving around / Settled / No signal | `LOUD`: "Louder than the set level for 3 minutes." The Sound tile and headline also say Excessive noise while any area is `LOUD`. |
| Node `ONLINE` / `STALE` / `OFFLINE` | Working / Delayed / Not connected | — |
| Mode `LECTURE` / `DISCUSSION` / `QUIET_WORK` | Class type: Lecture / Group work / Quiet work | — |
| Reference calibration | Voice setup | "Done" / "Not set up: the system tells lecturer and students apart by loudness only." |
| Loud levels (`loud_levels_x16`) | Noise limit | "Set for every area" / "Not set up. Noisy areas show as Talking." |
| Zone labels A–D | Lecturer's area, Front rows, Middle rows, Back rows | From `zone_layout` ([row, col], row 0 = front). A fifth sensor in the same row adds "door side" / "window side". |

Words to avoid on the main view: node, ppm, dBm, RTT, packet, calibrate, reference,
confidence %, fusion, stale. They may appear on the *Sensors* page and with technical names on.

## Feedback: what the system says and when

| Level | Look | Used for | Behaviour |
|---|---|---|---|
| Fine | ✓ circle, neutral | Normal states | No banner |
| Heads-up | ▲ triangle, amber | Getting noisy, Too warm/cold/humid/dry, a sensor delayed, Excessive noise in Group work | Shown in its tile; no banner |
| Act now | ■ square with "!", red | Ongoing chatter or Excessive noise (Lecture or Quiet work), Stuffy air, fewer than half the sensors working | Banner with one suggested action; entered in *What happened*; screen-reader announcement |

Severity depends on class type: chatter is *Act now* in Lecture and Quiet work, while
talking in Group work is *Fine*. In Quiet work, "Getting noisy" is a heads-up from the
first talking zone. Excessive noise is *Act now* ("Excessive noise in the back rows. Ask the
class to lower the volume.") except in Group work, where it is a heads-up: noise is
expected there, but a limit still says when it's too much.

Combined messages (fusion that a single sensor can't give):
- Stuffy + Room is empty → heads-up only: "Air is stuffy. Air the room before the next class."
- Ongoing chatter + Stuffy → one banner: "Ongoing chatter, and the air is stuffy. Fresh air may help: open a door or window."
- Too warm + most zones *Moving around* → heads-up: "Warm and restless."

Rules for alerts:
- An alert fires only after the engine's own hold time (20 s activity, 60 s air), so it doesn't flicker.
- It clears by itself when the state ends, and *What happened* records start and end.
- **Hide** removes the banner for 10 minutes but keeps it in *What happened*. A new or worse alert shows again.
- Alerts also go into the `--events` log, so the evaluator can report the alert count and time in alert.

## Actions and their feedback

- **Class type:** changing it shows "Switching to Group work…", then "All 4 sensors updated ✓",
  or "1 sensor didn't confirm, still trying". This uses the CONFIG ACK state the gateway
  already tracks. The current type is always visible.
- **Voice setup** (was Calibrate) is a short guided step: 1. "Ask only the lecturer to speak
  for about 30 seconds" → 2. a progress bar per area → 3. "Done ✓". There is **Cancel** at
  every step, and **Start over** (was Reset) asks for confirmation.
- **Noise limit** is a guided step like voice setup: an intro (open a sound-meter app, pick
  one steady sound at the target level), then one area at a time: "Area 1 of 3 · Front
  rows", which sensor to stand at, a live *Sensor hears* meter, **Capture** with a
  5-second countdown, then "Saved" with **Next area** or **Capture again**. Any area can be
  skipped and keeps showing Talking. The meter says when a sensor sends no sound, when the
  sound is too quiet, and when it nears the top of what the microphone can read (AC RMS of
  a 12-bit ADC can't pass about 2048 counts). A line on the meter marks the saved limit.
  **Remove all** asks for confirmation. The 70 dB target is a placeholder until a cited
  classroom noise limit replaces it.
- Every button says what it does ("Set up voice detection", not "Calibrate").

## HCI principles applied (Nielsen's heuristics)

| Heuristic | How the design meets it |
|---|---|
| Visibility of system status | Sensor summary and live indicator in the header on every page; current page marked; "Checking the room…" instead of a blank; feedback on every action |
| Match with the real world | Plain words, room positions instead of node IDs, "stuffy" instead of ppm |
| User control and freedom | Hide alert, Cancel and Start over in voice setup, class type always changeable |
| Consistency and standards | One icon and one colour per level everywhere; same label for a state in every place |
| Error prevention | Confirm before Start over; class-type buttons disabled while a change is in progress |
| Recognition over recall | The *why* line under every state; legend on the map; no codes to remember |
| Flexibility | Technical details and names for the team (Sensors page, technical names switch), simple Live room for the lecturer, presenter mode for a projector |
| Minimalist design | One headline, the room map and four small cards above the fold at 1366 × 768; the map replaces the three tiles that repeated the headline |
| Help users recover from errors | Messages say what to do: "Sensor at back left not connected. Check its power." |

## Accessibility (WCAG 2.2 AA)

- **Not colour alone:** every status has an icon shape, a word and a colour. Map cells use a
  pattern for *No signal*.
- **Contrast:** text at least 4.5:1, large text and icons at least 3:1, in light and dark themes.
- **Screen readers:** semantic landmarks and heading order; the headline is a `polite`
  live region announced **only when it changes**; new *Act now* alerts use `role="alert"`;
  the charts have a text summary ("CO₂ rose from 600 to 1,450 in 5 minutes").
- **Keyboard:** everything reachable with Tab, a visible 3 px focus ring, a skip link to the
  room status, Escape closes voice setup, and focus returns to the button that opened it.
- **Size and reflow:** body text at least 16 px, headline 40 px (readable from the back of a
  room on a projector), works at 200 % zoom and 320 px width without sideways scrolling,
  click targets at least 44 × 44 px.
- **Motion:** no flashing, and animation only when `prefers-reduced-motion` allows it.
- **Language:** `lang="en"`, short sentences, times as "2 min ago" with the exact time on hover.

## How we check it

1. Automated: a test fails if any engine state lacks a plain-language label, or if any colour
   pair in the theme tokens is below its contrast target.
2. Keyboard-only walkthrough and a VoiceOver pass (switch class type, run voice setup, hide an alert).
3. A 5-second test with 3 people outside the team: show the dashboard during the demo scenario
   and ask "What is happening in the room, and should the lecturer do anything?". Record
   answers in this file as evidence.
