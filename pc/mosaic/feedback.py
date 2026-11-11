"""Plain-language feedback: what the room is doing and what to do about it.

Presentation only, like the rest of dashboard.py: it reads the fusion states
and never feeds back into a decision. Engine names (FOCUSED_LECTURE, ...) stay
in code, logs and the evaluator; the page shows the words below. The wording,
severity levels and combined rules are specified in docs/ui_design.md.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Optional

FINE, HEADS_UP, ACT_NOW = "fine", "heads_up", "act_now"
_RANK = {FINE: 0, HEADS_UP: 1, ACT_NOW: 2}
HIDE_MS = 10 * 60 * 1000    # "Hide" keeps an alert off the banner this long
HISTORY = 50                # Ended alerts kept for the page
# Fusion states already have their own dwell. Sensor coverage doesn't, and
# sensors join one by one at start-up, so it must persist before it alerts.
ALERT_HOLD_MS = {"coverage": 15000}

ACTIVITY = {
    "UNKNOWN": "Checking the room…", "EMPTY": "Room is empty", "QUIET": "Quiet",
    "FOCUSED_LECTURE": "Lecture in progress", "NOISE_RISING": "Getting noisy",
    "SUSTAINED_CHATTER": "Ongoing chatter", "DISCUSSION": "Group discussion",
}
AIR = {"UNKNOWN": "No reading", "NORMAL": "Fresh", "POOR_VENTILATION": "Stuffy"}
COMFORT = {"UNKNOWN": "No reading", "COMFORTABLE": "Comfortable", "OUT_OF_RANGE": "Uncomfortable"}
ZONE_ACTIVITY = {"NO_DATA": "No signal", "STILL": "Settled", "MOTION": "Moving around",
                 "LECTURER": "Lecturer speaking", "TALKING": "Talking"}
ZONE_AIR = {"UNKNOWN": "No reading", "GOOD": "Fresh", "FAIR": "Getting stuffy", "POOR": "Stuffy"}
SENSOR = {"ONLINE": "Working", "STALE": "Delayed", "OFFLINE": "Not connected"}
MODE = {"LECTURE": "Lecture", "DISCUSSION": "Group work", "QUIET_WORK": "Quiet work"}


def activity_level(activity: str, mode: str) -> str:
    """Severity depends on the class type (docs/ui_design.md, Feedback)."""
    if activity == "SUSTAINED_CHATTER":
        return FINE if mode == "DISCUSSION" else ACT_NOW
    if activity == "NOISE_RISING":
        return HEADS_UP
    if activity == "FOCUSED_LECTURE" and mode == "QUIET_WORK":
        return HEADS_UP
    return FINE


def worst(*levels: str) -> str:
    return max(levels, key=_RANK.__getitem__, default=FINE)


def join(words: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def duration(ms: int) -> str:
    minutes = max(0, ms) // 60000
    if minutes < 1:
        return "less than a minute"
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def zone_names(zones: list[dict]) -> dict[str, str]:
    """Room areas from the zone layout ([row, col]): row 0 is the front of the
    room, rows run towards the back, and columns run from the door side to the
    window side. The reference zone is the lecturer's area; the student rows
    are front, middle and back rows."""
    names = {}
    students = [z for z in zones if not z.get("reference_zone")]
    for z in zones:
        if z.get("reference_zone"):
            names[z["zone"]] = "Lecturer's area"
    rows = sorted({z["layout"][0] for z in students})
    for z in students:
        row, col = z["layout"]
        i = rows.index(row)
        if len(rows) == 1:
            name = "Seating"
        elif i == 0:
            name = "Front rows"
        elif i == len(rows) - 1:
            name = "Back rows"
        else:
            name = "Middle rows" if len(rows) == 3 else f"Row group {i + 1}"
        cols = sorted(s["layout"][1] for s in students if s["layout"][0] == row)
        if len(cols) > 1:
            name += (", door side" if col == cols[0] else ", window side" if col == cols[-1]
                     else ", centre")
        names[z["zone"]] = name
    return names


def place(name: str) -> str:
    """'Back rows' -> 'the back rows', for sentences."""
    return "the " + name[0].lower() + name[1:]


def _mean(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _sensors(zones: list[dict], names: dict[str, str], reported: bool) -> dict:
    total = len(zones)
    working = [z for z in zones if z["status"] == "ONLINE"]
    delayed = [names[z["zone"]] for z in zones if z["status"] == "STALE"]
    missing = [names[z["zone"]] for z in zones if z["status"] == "OFFLINE"]
    if not reported:
        text, level = "No sensors connected yet", HEADS_UP
    elif not delayed and not missing:
        text, level = f"All {total} sensors working", FINE
    else:
        parts = []
        if missing:
            parts.append(f"{len(missing)} not connected ({join(missing).lower()})")
        if delayed:
            parts.append(f"{len(delayed)} delayed ({join(delayed).lower()})")
        text, level = f"{len(working)} of {total} sensors working: " + "; ".join(parts), HEADS_UP
    low = reported and (len(working) + len(delayed)) * 2 < total
    return {"text": text, "level": ACT_NOW if low else level, "working": len(working),
            "total": total, "low_coverage": low}


def _voice(reference: dict, names: dict[str, str]) -> dict:
    """Voice setup (lecturer-reference calibration) in plain words."""
    if not reference or not reference.get("enabled"):
        return {"enabled": False, "state": "off", "text": "Voice setup is not available for this room layout.",
                "zones": []}
    zones = []
    for zone, s in reference["zones"].items():
        done = s.get("gain_q16") is not None
        busy = not done and (s.get("state") == "CALIBRATING" or (s.get("pairs_collected") or 0) > 0)
        need = s.get("required_pairs") or 1
        zones.append({"zone": zone, "name": names.get(zone, zone), "done": done, "in_progress": busy,
                      "progress_pct": 100 if done else min(99, 100 * (s.get("pairs_collected") or 0) // need)})
    if zones and all(z["done"] for z in zones):
        state, text = "done", "Done. The system tells the lecturer and students apart by where the voice is loudest."
    elif any(z["in_progress"] for z in zones):
        state, text = "in_progress", "Listening… keep only the lecturer speaking."
    elif any(z["done"] for z in zones):
        state, text = "partial", "Set up for some areas only. Run it again to include every area."
    else:
        state, text = "not_set_up", ("Not set up. The system tells the lecturer and students apart by "
                                     "loudness only, which is less reliable.")
    return {"enabled": True, "state": state, "text": text, "zones": zones,
            "lecturer_area": names.get(reference.get("zone"), reference.get("zone"))}


def describe(c: dict, nodes: list[dict], events: list[dict] = (), wall_ms: int = 0) -> dict:
    """Everything the page says about the room. `c` is present_classroom()
    output, `nodes` the dashboard's node list, `events` fusion state changes as
    dicts with wall_ms. Returns plain-language text plus the engine names
    under 'tech' for the optional technical view."""
    zones = c["zones"]
    names = zone_names(zones)
    mode, activity, air, comfort = c["mode"], c["activity"], c["air"], c["comfort"]
    now_ms = c.get("now_ms", 0)
    sensors = _sensors(zones, names, bool(nodes))
    talking = [names[z["zone"]] for z in zones if z["state"] == "TALKING"]
    where = join([place(n) for n in talking]) or "some desks"
    # How long people have been talking: from the first area that started, not
    # from when the classroom state escalated to chatter.
    talk_since = min([z.get("since_ms", now_ms) for z in zones if z["state"] == "TALKING"]
                     or [c.get("activity_since_ms", now_ms)])
    warming = any((n.get("telemetry") or {}).get("co2_warmup") for n in nodes if n["status"] != "offline")

    # Sound
    sound_level = activity_level(activity, mode)
    sound_why = {
        "UNKNOWN": ("Waiting for enough readings (about 20 seconds)." if sensors["working"]
                    else "No sensors are sending readings yet."),
        "EMPTY": "No movement or voices for a while.",
        "QUIET": "People are here, but no one is talking much.",
        "FOCUSED_LECTURE": ("Someone is speaking at the lecturer's desk." if mode == "QUIET_WORK"
                            else "The lecturer is speaking and students are quiet."),
        "NOISE_RISING": f"Talking in {where}.",
        "SUSTAINED_CHATTER": f"Talking in {where} for {duration(now_ms - talk_since)}.",
        "DISCUSSION": "Most groups are talking, as expected in group work.",
    }.get(activity, "")

    # Air
    co2 = [(z["co2_ppm"], names[z["zone"]]) for z in zones if z.get("co2_ppm") is not None]
    peak = max(co2) if co2 else None
    if air == "POOR_VENTILATION":
        empty = activity == "EMPTY"
        air_level = HEADS_UP if empty else ACT_NOW
        air_label = "Stuffy"
        air_why = ("Air the room before the next class." if empty else
                   f"Stuffiest in {place(peak[1])}. Open a door or window." if peak else
                   "Open a door or window.")
    elif air == "NORMAL":
        air_level, air_label, air_why = FINE, "Fresh", "The air is fine in every area."
    else:
        air_level = FINE
        air_label = "Sensor warming up" if warming else "No reading"
        air_why = "Air quality is ready in a few minutes." if warming else "No air sensor is reporting."

    # Comfort
    temp = _mean([z.get("temperature_c") for z in zones if z["status"] != "OFFLINE"])
    hum = _mean([z.get("humidity_pct") for z in zones if z["status"] != "OFFLINE"])
    reading = (f"{temp:.1f} °C, {hum:.0f} % humidity." if temp is not None and hum is not None else "")
    reasons = c.get("comfort_reasons") or []
    if comfort == "OUT_OF_RANGE":
        comfort_level = HEADS_UP
        comfort_label = join(reasons).capitalize() if reasons else "Uncomfortable"
        moving = sum(z["state"] == "MOTION" for z in zones)
        restless = "too warm" in reasons and zones and moving * 2 >= len(zones)
        comfort_why = ("Warm and restless: cooling the room may help. " + reading).strip() if restless else reading
    else:
        comfort_level = FINE
        comfort_label = COMFORT.get(comfort, comfort)
        comfort_why = reading if comfort == "COMFORTABLE" else "No temperature sensor is reporting."

    tiles = [
        {"id": "sound", "title": "Sound", "label": ACTIVITY.get(activity, activity), "level": sound_level,
         "why": sound_why, "tech": activity},
        {"id": "air", "title": "Air", "label": air_label, "level": air_level, "why": air_why,
         "detail": f"Highest CO₂ {peak[0]} ppm" if peak else "", "tech": air},
        {"id": "comfort", "title": "Comfort", "label": comfort_label, "level": comfort_level,
         "why": comfort_why, "tech": comfort},
    ]

    summary = [sound_why,
               {"NORMAL": "The air is fresh.", "POOR_VENTILATION": "The air is stuffy."}.get(
                   air, "Air quality isn't available yet."),
               ("Temperature is comfortable." if comfort == "COMFORTABLE" else
                f"It's {join(reasons)}." if comfort == "OUT_OF_RANGE" and reasons else "")]

    return {
        "headline": ACTIVITY.get(activity, activity),
        "summary": " ".join(s for s in summary if s),
        "level": worst(sound_level, air_level, comfort_level, sensors["level"]),
        "tech": {"activity": activity, "air": air, "comfort": comfort, "mode": mode},
        "mode": {"value": mode, "label": MODE.get(mode, mode)},
        "sensors": sensors,
        "tiles": tiles,
        "zones": [_zone(z, names, now_ms) for z in zones],
        "voice": _voice(c.get("reference"), names),
        "timeline": [_timeline(e, mode) for e in reversed(events)],
        "alerts_wanted": _alerts(activity, air, mode, where, sensors, peak, names),
    }


def _zone(z: dict, names: dict[str, str], now_ms: int) -> dict:
    state, status = z["state"], z["status"]
    if status == "OFFLINE":
        label, level, why = "Not connected", "none", "Check that this sensor is powered."
    elif state == "TALKING":
        label, level, why = "Talking", HEADS_UP, f"For {duration(now_ms - z.get('since_ms', now_ms))}."
    elif state == "NO_DATA":
        label, level, why = "No signal", "none", "No sound reading from this sensor."
    else:
        label, level = ZONE_ACTIVITY.get(state, state), FINE
        why = "Where the lecturer's voice is loudest." if z.get("reference_zone") and state == "LECTURER" else ""
    if status == "STALE":
        why = ("Readings are delayed. " + why).strip()
    air_level = {"POOR": ACT_NOW, "FAIR": HEADS_UP, "GOOD": FINE}.get(z["air"], "none")
    comfort_level = {"OUT_OF_RANGE": HEADS_UP, "COMFORTABLE": FINE}.get(z["comfort"], "none")
    motion = z.get("motion_active")
    return {
        "zone": z["zone"], "name": names[z["zone"]], "node_id": z["node_id"], "layout": z["layout"],
        "lecturer_area": bool(z.get("reference_zone")), "status": SENSOR.get(status, status),
        "status_level": {"ONLINE": FINE, "STALE": HEADS_UP}.get(status, "none"),
        "activity": {"label": label, "level": level, "why": why, "tech": state},
        "air": {"label": ZONE_AIR.get(z["air"], z["air"]), "level": air_level,
                "detail": f"{z['co2_ppm']} ppm CO₂" if z.get("co2_ppm") is not None else "", "tech": z["air"]},
        "comfort": {"label": COMFORT.get(z["comfort"], z["comfort"]), "level": comfort_level,
                    "detail": (f"{z['temperature_c']:.1f} °C · {z['humidity_pct']:.0f} %"
                               if z.get("temperature_c") is not None else ""), "tech": z["comfort"]},
        "motion": {"label": "No reading" if motion is None else "Moving around" if motion else "Still",
                   "level": "none" if motion is None else HEADS_UP if motion else FINE,
                   "detail": f"{z['motion_pct']} % of the time" if z.get("motion_pct") is not None else ""},
    }


def _timeline(e: dict, mode: str) -> dict:
    region, old, new = e["region"], e["old"], e["new"]
    if region == "activity":
        text, level = ACTIVITY.get(new, new).rstrip("…"), activity_level(new, mode)
    elif region == "air":
        text = {"POOR_VENTILATION": "Air became stuffy",
                "NORMAL": "Air is fresh again" if old == "POOR_VENTILATION" else "Air is fresh",
                "UNKNOWN": "Air reading not available"}.get(new, new)
        level = ACT_NOW if new == "POOR_VENTILATION" else FINE
    elif region == "comfort":
        text = {"OUT_OF_RANGE": "Room became uncomfortable",
                "COMFORTABLE": "Comfortable again" if old == "OUT_OF_RANGE" else "Comfortable",
                "UNKNOWN": "Temperature reading not available"}.get(new, new)
        level = HEADS_UP if new == "OUT_OF_RANGE" else FINE
    elif region == "mode":
        text, level = f"Class type changed to {MODE.get(new, new)}", FINE
    else:
        text, level = new, FINE
    return {"wall_ms": e["wall_ms"], "text": text, "level": level,
            "tech": f"{region}: {old} → {new}"}


def _alerts(activity: str, air: str, mode: str, where: str, sensors: dict,
            peak: Optional[tuple], names: dict) -> dict[str, dict]:
    """Act-now conditions, keyed so the same situation keeps one alert."""
    wanted = {}
    chatter = activity == "SUSTAINED_CHATTER" and mode != "DISCUSSION"
    stuffy = air == "POOR_VENTILATION" and activity != "EMPTY"
    if chatter and stuffy:
        wanted["chatter_air"] = {"message": "Ongoing chatter, and the air is stuffy.",
                                 "action": "Fresh air may help: open a door or window."}
    elif chatter:
        # While chatter winds down the areas may already be quiet; "some desks"
        # must not overwrite the places the alert named (vague: keep old text).
        wanted["chatter"] = {"message": f"Ongoing chatter in {where}.",
                             "action": "Consider re-engaging the class.", "vague": where == "some desks"}
    elif stuffy:
        near = f" Stuffiest in {place(peak[1])}." if peak else ""
        wanted["air"] = {"message": "The air is stuffy." + near, "action": "Open a door or window."}
    if sensors["low_coverage"]:
        wanted["coverage"] = {"message": "Fewer than half the sensors are working, so readings may be wrong.",
                              "action": "Check that the sensors are powered and on the hotspot."}
    return wanted


class AlertLog:
    """Act-now alerts: start when a condition appears, end when it clears.

    'Hide' keeps one alert off the banner for HIDE_MS; it stays in the log and
    a different (new or worse) alert still shows. A key in ALERT_HOLD_MS must be
    wanted continuously that long before it starts. `log(event, fields)`
    records start/end/hide for the --events evaluation log.
    """

    def __init__(self, log: Optional[Callable[[str, dict], None]] = None) -> None:
        self.active: dict[str, dict] = {}
        self._pending: dict[str, int] = {}  # key -> first wanted, for held keys
        self.ended: deque[dict] = deque(maxlen=HISTORY)
        self._next_id = 1
        self._log = log or (lambda event, fields: None)

    def update(self, wanted: dict[str, dict], wall_ms: int) -> None:
        for key in [k for k in self.active if k not in wanted]:
            alert = self.active.pop(key)
            alert["ended_ms"] = wall_ms
            self.ended.append(alert)
            self._log("end", {"id": alert["id"], "key": key})
        self._pending = {k: t for k, t in self._pending.items() if k in wanted}
        for key, text in wanted.items():
            text = dict(text)
            vague = text.pop("vague", False)
            if key in self.active:
                if not vague:
                    self.active[key].update(text)  # e.g. the talking areas changed
                continue
            first = self._pending.setdefault(key, wall_ms)
            if wall_ms - first < ALERT_HOLD_MS.get(key, 0):
                continue
            del self._pending[key]
            alert = {"id": self._next_id, "key": key, "level": ACT_NOW, "started_ms": wall_ms,
                     "ended_ms": None, "hidden_until_ms": None, **text}
            self._next_id += 1
            self.active[key] = alert
            self._log("start", {"id": alert["id"], "key": key, "message": alert["message"]})

    def hide(self, alert_id: int, wall_ms: int) -> bool:
        for alert in self.active.values():
            if alert["id"] == alert_id:
                alert["hidden_until_ms"] = wall_ms + HIDE_MS
                self._log("hide", {"id": alert_id, "key": alert["key"]})
                return True
        return False

    def view(self, wall_ms: int) -> dict:
        active = sorted(self.active.values(), key=lambda a: -a["started_ms"])
        shown = [a for a in active if not a["hidden_until_ms"] or a["hidden_until_ms"] <= wall_ms]
        return {"banner": shown, "hidden": len(active) - len(shown), "active": active,
                "ended": list(reversed(self.ended))}
