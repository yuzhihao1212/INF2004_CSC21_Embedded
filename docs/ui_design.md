# Dashboard design: plain language, HCI and accessibility

The dashboard has two audiences. A **lecturer** glances at it mid-class, often from a
distance, and needs one answer: *is the room OK, and should I do anything?* The **team or
technician** needs node health, calibration and raw readings. The design serves the
lecturer first and keeps technical detail one click away (progressive disclosure).

## Pages

The dashboard is split into five pages so each one answers one question. Navigation is
a labelled bar under the logo (a bottom bar on phones); the current page is marked with
`aria-current`, the browser title names the page, Back/Forward work (`#/map`, ...), and
focus moves to the page heading so screen-reader users hear where they are. The *act now*
banner appears above every page.

| Page | Question it answers | Contents |
|---|---|---|
| Overview | Is the room OK, and should I do anything? | Headline + summary, Sound/Air/Comfort tiles, class type, room at a glance, latest 4 changes |
| Room map | Where is it happening? | Floor plan of the classroom (front wall with whiteboard, lecturer's desk, door, windows, desks, sensor dots) with each area tinted by level; switch sound, air, temperature, movement; select an area for all its readings. On narrow screens the plan turns so the front is at the top. |
| History | What happened? | Full timeline incl. cleared alerts; CO₂ and temperature charts with a text summary |
| Sensors | Is the equipment working? | Per-sensor readings, sound class, Wi-Fi signal, lost readings, response time |
| Setup | How do I change it? | Class type, voice setup (guided), report interval, technical names, theme |

```
┌ mosaic   ⌂ Overview │ ▦ Room map │ ↺ History │ ((•)) Sensors │ ⚙ Setup   ✓ All 4 sensors working ┐
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ ■! Ongoing chatter at back right.  Consider re-engaging the class.          [Hide 10 min] │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ Overview                                     Class type: (Lecture) Group work Quiet work  │
│ ┃ Ongoing chatter                                                                         │
│ ┃ Talking at back right for 3 minutes. The air is fresh. Temperature is comfortable.      │
│ [Sound ■ Ongoing chatter] [Air ✓ Fresh] [Comfort ✓ Comfortable]                           │
│ [Room at a glance: small floor plan]           [What happened: 10:47 … 10:44 …]            │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Plain-language labels

The engine's names stay in code, logs and the evaluator. The screen shows the words
on the right. A **Show technical names** switch on the *Setup* page adds the
engine name in brackets, so we can map the screen to the statechart in the tribunal.

| Engine state | Headline / label | Summary or "why" line (example) |
|---|---|---|
| Activity `UNKNOWN` | Checking the room… | "Waiting for enough readings (about 20 s)." Not "No data" when sensors are working. |
| `EMPTY` | Room is empty | "No one has been detected for 10 minutes." |
| `QUIET` | Quiet | "People are here, no one is talking much." |
| `FOCUSED_LECTURE` | Lecture in progress | "The lecturer is speaking and students are quiet." |
| `NOISE_RISING` | Getting noisy | "Talking at the back right." |
| `SUSTAINED_CHATTER` | Ongoing chatter | "Talking at the back right for 2 minutes." |
| `DISCUSSION` | Group discussion | "Most groups are talking, as expected in group work." |
| Air `NORMAL` / `POOR_VENTILATION` / `UNKNOWN` | Fresh / Stuffy / Sensor warming up | "Highest near the back left." / "Ready in about 3 minutes." |
| Comfort `COMFORTABLE` / `OUT_OF_RANGE` / `UNKNOWN` | Comfortable / Too warm, Too cold, Too humid, Too dry / No reading | Direction comes from which limit was crossed. |
| Zone `LECTURER` / `TALKING` / `MOTION` / `STILL` / `NO_DATA` | Lecturer speaking / Talking / Moving around / Settled / No signal | — |
| Node `ONLINE` / `STALE` / `OFFLINE` | Working / Delayed / Not connected | — |
| Mode `LECTURE` / `DISCUSSION` / `QUIET_WORK` | Class type: Lecture / Group work / Quiet work | — |
| Reference calibration | Voice setup | "Done" / "Not set up: the system tells lecturer and students apart by loudness only." |
| Zone labels A–D | Lecturer's area, Front rows, Middle rows, Back rows | From `zone_layout` ([row, col], row 0 = front). A fifth sensor in the same row adds "door side" / "window side". |

Words to avoid on the main view: node, ppm, dBm, RTT, packet, calibrate, reference,
confidence %, fusion, stale. They may appear on the *Sensors* page and with technical names on.

## Feedback: what the system says and when

| Level | Look | Used for | Behaviour |
|---|---|---|---|
| Fine | ✓ circle, neutral | Normal states | No banner |
| Heads-up | ▲ triangle, amber | Getting noisy, Too warm/cold/humid/dry, a sensor delayed | Shown in its tile; no banner |
| Act now | ■ square with "!", red | Ongoing chatter (Lecture or Quiet work), Stuffy air, fewer than half the sensors working | Banner with one suggested action; entered in *What happened*; screen-reader announcement |

Severity depends on class type: chatter is *Act now* in Lecture and Quiet work, while
talking in Group work is *Fine*. In Quiet work, "Getting noisy" is a heads-up from the
first talking zone.

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
| Flexibility | Technical details and names for the team (Sensors page, technical names switch), simple Overview for the lecturer |
| Minimalist design | One headline, three tiles, a map and a short history above the fold |
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
