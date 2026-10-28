"""MOSAIC fusion engine: classroom states from every zone's TELEMETRY.

Implements the Week 6 design's statechart 6.4 on the PC. Three regions run in
parallel, so the room can be in FOCUSED_LECTURE, POOR_VENTILATION and
OUT_OF_RANGE at the same time:

  Activity  UNKNOWN | EMPTY | OCCUPIED, and inside OCCUPIED:
            QUIET | FOCUSED_LECTURE | DISCUSSION | NOISE_RISING | SUSTAINED_CHATTER
  Air       UNKNOWN | NORMAL | POOR_VENTILATION
  Comfort   UNKNOWN | COMFORTABLE | OUT_OF_RANGE

Rules:
- Audio class probabilities are averaged per zone over audio_smooth_s, so a
  single window (a cough, a dropped book) never changes state.
- Every change needs its condition to hold for a dwell time.
- Enter and exit thresholds differ (hysteresis), so a value hovering at a
  threshold doesn't make the state flicker.
- PIR measures motion, not presence: a still, seated class reads low. So
  speech and raised CO2 also count as evidence the room is occupied, and
  EMPTY needs a long quiet period (empty_after_s).
- The operating mode changes the rules. In DISCUSSION mode, conversation
  across zones is DISCUSSION rather than NOISE_RISING. QUIET_WORK uses lower
  conversation thresholds.
- Only ONLINE and STALE zones are used; confidence drops while any configured
  zone is missing or STALE.

Every threshold lives in FusionConfig and can be overridden from a JSON file
(--fusion-config), to be tuned with scripted scenarios. FusionEngine takes the
current time as an argument, like Gateway, so it is tested without sleeping.
"""

from __future__ import annotations

import enum
import json
from collections import deque
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from mosaic import protocol as p

EVENT_HISTORY = 50


class Activity(enum.Enum):
    UNKNOWN = "UNKNOWN"                      # No fresh zone data
    EMPTY = "EMPTY"
    QUIET = "QUIET"                          # Occupied, no dominant activity (e.g. quiet work)
    FOCUSED_LECTURE = "FOCUSED_LECTURE"
    DISCUSSION = "DISCUSSION"                # Only in DISCUSSION mode
    NOISE_RISING = "NOISE_RISING"
    SUSTAINED_CHATTER = "SUSTAINED_CHATTER"  # NOISE_RISING that persisted

    @property
    def occupied(self) -> bool:
        return self not in (Activity.UNKNOWN, Activity.EMPTY)


_NOISY = (Activity.DISCUSSION, Activity.NOISE_RISING, Activity.SUSTAINED_CHATTER)


class Air(enum.Enum):
    UNKNOWN = "UNKNOWN"  # No valid CO2 (all warming up, or no fresh zone)
    NORMAL = "NORMAL"
    POOR_VENTILATION = "POOR_VENTILATION"


class Comfort(enum.Enum):
    UNKNOWN = "UNKNOWN"
    COMFORTABLE = "COMFORTABLE"
    OUT_OF_RANGE = "OUT_OF_RANGE"


@dataclass
class FusionConfig:
    """Default profile. Values are design defaults to be tuned (assumption A5)."""
    # node_id -> zone label. Front zones are the lecturer area.
    zones: dict[int, str] = field(default_factory=lambda: {1: "A", 2: "B", 3: "C", 4: "D"})
    front_zones: tuple[str, ...] = ("A", "B")
    mode: p.Mode = p.Mode.LECTURE

    audio_smooth_s: float = 10.0       # Class probabilities averaged over this
    motion_window_s: float = 60.0      # PIR motion averaged over this

    # Occupancy
    motion_pct_min: int = 10           # Zone motion that counts as evidence
    voice_pct_min: int = 40            # Speech + conversation that counts as evidence
    co2_occupied_ppm: int = 800        # CO2 this high keeps the room OCCUPIED (still class)
    occupied_after_s: float = 20.0
    empty_after_s: float = 600.0

    # Activity inside OCCUPIED (smoothed probabilities, %)
    lecture_speech_pct: int = 50       # Lecturer speech in a front zone
    conversation_enter_pct: int = 40
    conversation_exit_pct: int = 25
    quiet_work_conversation_enter_pct: int = 25
    quiet_work_conversation_exit_pct: int = 15
    widespread_fraction: float = 0.5   # Share of zones with conversation for "across zones"
    activity_dwell_s: float = 20.0
    chatter_after_s: float = 120.0     # NOISE_RISING this long becomes SUSTAINED_CHATTER

    # Air
    co2_poor_ppm: int = 1200
    co2_recovered_ppm: int = 1000      # POOR_VENTILATION exits below this
    air_dwell_s: float = 60.0

    # Comfort (classroom mean)
    temp_min_c: float = 20.0
    temp_max_c: float = 28.0
    humidity_min_pct: float = 30.0
    humidity_max_pct: float = 70.0
    temp_hysteresis_c: float = 0.5     # Must be this far inside the range to exit
    humidity_hysteresis_pct: float = 3.0
    comfort_dwell_s: float = 60.0

    @classmethod
    def from_json(cls, path: str | Path) -> FusionConfig:
        """Defaults overridden by the keys in a JSON object. Unknown keys
        are an error, so a typo doesn't silently keep the default."""
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fusion settings: {', '.join(sorted(unknown))}")
        if "zones" in data:
            data["zones"] = {int(node): str(zone) for node, zone in data["zones"].items()}
        if "front_zones" in data:
            data["front_zones"] = tuple(data["front_zones"])
        if "mode" in data:
            data["mode"] = p.Mode[data["mode"].upper()]
        return cls(**data)


@dataclass
class ZoneView:
    """One zone's smoothed inputs, as used by the rules."""
    zone: str
    node_id: int
    probs: Optional[tuple[float, ...]]  # Mean prob_pct per class 1..4; None without audio
    motion_pct: Optional[float]
    co2_ppm: Optional[int]
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    stale: bool

    def prob(self, audio_class: p.AudioClass) -> float:
        return self.probs[audio_class - 1] if self.probs else 0.0


@dataclass
class Event:
    time: float
    region: str
    old: str
    new: str
    reason: str


class _Zone:
    def __init__(self) -> None:
        self.audio: deque[tuple[float, tuple[int, ...]]] = deque()
        self.motion: deque[tuple[float, int]] = deque()
        self.co2: Optional[int] = None
        self.temp_hum: Optional[tuple[float, float]] = None


class _Region:
    """One statechart region: a change happens once the same candidate
    state has been proposed continuously for its dwell time."""

    def __init__(self, name: str, state: enum.Enum) -> None:
        self.name = name
        self.state = state
        self.since = 0.0
        self._candidate: Optional[enum.Enum] = None
        self._candidate_since = 0.0

    def propose(self, candidate: enum.Enum, now: float, dwell: float) -> bool:
        if candidate == self.state:
            self._candidate = None
            return False
        if candidate != self._candidate:
            self._candidate, self._candidate_since = candidate, now
        if now - self._candidate_since < dwell:
            return False
        self.state, self.since, self._candidate = candidate, now, None
        return True


class FusionEngine:
    def __init__(self, config: Optional[FusionConfig] = None) -> None:
        self.config = config or FusionConfig()
        self.mode = self.config.mode
        self._zones: dict[int, _Zone] = {}
        self.activity = _Region("activity", Activity.UNKNOWN)
        self.air = _Region("air", Air.UNKNOWN)
        self.comfort = _Region("comfort", Comfort.UNKNOWN)
        self.comfort_reasons: list[str] = []
        self.events: deque[Event] = deque(maxlen=EVENT_HISTORY)
        self._views: list[ZoneView] = []
        self._confidence = 0.0
        self._pending: list[Event] = []  # New events since drain_events()

    # ---- Inputs ------------------------------------------------------------

    def add(self, node_id: int, t: p.Telemetry, now: float) -> None:
        """Record one TELEMETRY. Nodes not in config.zones are ignored."""
        if node_id not in self.config.zones:
            return
        zone = self._zones.setdefault(node_id, _Zone())
        for window in t.audio:
            zone.audio.append((now, window.prob_pct))
        if p.Valid.PIR in t.valid_flags:
            zone.motion.append((now, t.pir_active_pct))
        # Invalid readings clear the value: never fuse a stale or warming-up value.
        zone.co2 = t.co2_ppm if p.Valid.CO2 in t.valid_flags else None
        zone.temp_hum = ((t.temperature_c, t.humidity_pct)
                         if p.Valid.TEMP_HUM in t.valid_flags else None)

    def set_mode(self, mode: p.Mode, now: float) -> None:
        if mode != self.mode:
            self._event(now, "mode", self.mode.name, mode.name, "operator")
            self.mode = mode

    # ---- Evaluation ----------------------------------------------------------

    def evaluate(self, now: float, online: set[int], stale: set[int] = frozenset()) -> None:
        """Re-run the rules. `online` and `stale` are the node IDs the gateway
        reports in those states; OFFLINE nodes are simply absent."""
        cfg = self.config
        self._views = [self._view(node_id, now, node_id in stale)
                       for node_id in sorted(self._zones)
                       if node_id in online or node_id in stale]
        fresh = len(self._views) - sum(v.stale for v in self._views)
        # A STALE zone counts half: its data is up to 10 s old.
        self._confidence = (fresh + 0.5 * (len(self._views) - fresh)) / max(1, len(cfg.zones))
        self._step_activity(now)
        self._step_air(now)
        self._step_comfort(now)

    def _view(self, node_id: int, now: float, stale: bool) -> ZoneView:
        cfg, zone = self.config, self._zones[node_id]
        _trim(zone.audio, now - cfg.audio_smooth_s)
        _trim(zone.motion, now - cfg.motion_window_s)
        probs = None
        if zone.audio:
            probs = tuple(sum(w[1][i] for w in zone.audio) / len(zone.audio)
                          for i in range(p.AUDIO_CLASS_COUNT))
        motion = sum(m for _, m in zone.motion) / len(zone.motion) if zone.motion else None
        temp, hum = zone.temp_hum or (None, None)
        return ZoneView(cfg.zones[node_id], node_id, probs, motion, zone.co2, temp, hum, stale)

    def _step_activity(self, now: float) -> None:
        cfg, views = self.config, self._views
        if not views:
            self._force(self.activity, Activity.UNKNOWN, now, "no zone data")
            return
        state = self.activity.state

        evidence = []
        for v in views:
            if v.motion_pct is not None and v.motion_pct >= cfg.motion_pct_min:
                evidence.append(f"motion in {v.zone}")
            voice = v.prob(p.AudioClass.LECTURER_SPEECH) + v.prob(p.AudioClass.STUDENT_CONVERSATION)
            if voice >= cfg.voice_pct_min:
                evidence.append(f"voices in {v.zone}")
        # CO2 only keeps the room occupied; it lags too much to declare it so.
        if state.occupied and any(v.co2_ppm and v.co2_ppm >= cfg.co2_occupied_ppm for v in views):
            evidence.append("raised CO2")

        if not evidence:
            dwell = cfg.empty_after_s if state.occupied else cfg.occupied_after_s
            self._propose(self.activity, Activity.EMPTY, now, dwell, "no motion, voices or raised CO2")
            return
        if not state.occupied:
            self._propose(self.activity, Activity.QUIET, now, cfg.occupied_after_s,
                          ", ".join(evidence))
            return

        candidate, reason = self._occupied_candidate(state, now)
        dwell = 0.0 if candidate == Activity.SUSTAINED_CHATTER else cfg.activity_dwell_s
        self._propose(self.activity, candidate, now, dwell, reason)

    def _occupied_candidate(self, state: Activity, now: float) -> tuple[Activity, str]:
        cfg, views = self.config, self._views
        quiet_work = self.mode == p.Mode.QUIET_WORK
        if state in _NOISY:  # Lower bar to stay than to enter
            threshold = cfg.quiet_work_conversation_exit_pct if quiet_work else cfg.conversation_exit_pct
        else:
            threshold = (cfg.quiet_work_conversation_enter_pct if quiet_work
                         else cfg.conversation_enter_pct)

        audio_views = [v for v in views if v.probs]
        talking = [v.zone for v in audio_views
                   if v.prob(p.AudioClass.STUDENT_CONVERSATION) >= threshold]
        widespread = bool(audio_views) and (
            len(talking) / len(audio_views) >= cfg.widespread_fraction)
        rear_talking = [z for z in talking if z not in cfg.front_zones]

        if self.mode == p.Mode.DISCUSSION:
            if widespread:
                return Activity.DISCUSSION, f"conversation in {', '.join(talking)}"
        elif widespread or rear_talking:
            reason = f"conversation in {', '.join(talking)}"
            if state == Activity.SUSTAINED_CHATTER:
                return Activity.SUSTAINED_CHATTER, reason
            if state == Activity.NOISE_RISING and now - self.activity.since >= cfg.chatter_after_s:
                return Activity.SUSTAINED_CHATTER, f"{reason} for {cfg.chatter_after_s:.0f} s"
            return Activity.NOISE_RISING, reason

        front = [v for v in audio_views if v.zone in cfg.front_zones] or audio_views
        lecturer = [v.zone for v in front
                    if v.prob(p.AudioClass.LECTURER_SPEECH) >= cfg.lecture_speech_pct]
        if lecturer:
            return Activity.FOCUSED_LECTURE, f"lecturer speech in {', '.join(lecturer)}"
        return Activity.QUIET, "no dominant activity"

    def _step_air(self, now: float) -> None:
        cfg = self.config
        readings = [(v.co2_ppm, v.zone) for v in self._views if v.co2_ppm is not None]
        if not readings:
            self._force(self.air, Air.UNKNOWN, now, "no valid CO2 reading")
            return
        ppm, zone = max(readings)
        if self.air.state == Air.POOR_VENTILATION:
            candidate = Air.NORMAL if ppm < cfg.co2_recovered_ppm else Air.POOR_VENTILATION
        else:
            candidate = Air.POOR_VENTILATION if ppm >= cfg.co2_poor_ppm else Air.NORMAL
        dwell = 0.0 if self.air.state == Air.UNKNOWN else cfg.air_dwell_s
        self._propose(self.air, candidate, now, dwell, f"CO2 {ppm} ppm in {zone}")

    def _step_comfort(self, now: float) -> None:
        cfg = self.config
        readings = [(v.temperature_c, v.humidity_pct) for v in self._views
                    if v.temperature_c is not None]
        if not readings:
            self.comfort_reasons = []
            self._force(self.comfort, Comfort.UNKNOWN, now, "no valid temperature reading")
            return
        temp = sum(t for t, _ in readings) / len(readings)
        hum = sum(h for _, h in readings) / len(readings)
        # Inside the range by the hysteresis margin to leave OUT_OF_RANGE.
        margin_t = cfg.temp_hysteresis_c if self.comfort.state == Comfort.OUT_OF_RANGE else 0.0
        margin_h = cfg.humidity_hysteresis_pct if self.comfort.state == Comfort.OUT_OF_RANGE else 0.0
        reasons = []
        if temp > cfg.temp_max_c - margin_t:
            reasons.append(f"too warm ({temp:.1f} °C)")
        if temp < cfg.temp_min_c + margin_t:
            reasons.append(f"too cold ({temp:.1f} °C)")
        if hum > cfg.humidity_max_pct - margin_h:
            reasons.append(f"too humid ({hum:.0f} %RH)")
        if hum < cfg.humidity_min_pct + margin_h:
            reasons.append(f"too dry ({hum:.0f} %RH)")
        candidate = Comfort.OUT_OF_RANGE if reasons else Comfort.COMFORTABLE
        dwell = 0.0 if self.comfort.state == Comfort.UNKNOWN else cfg.comfort_dwell_s
        self._propose(self.comfort, candidate, now, dwell,
                      "; ".join(reasons) or f"{temp:.1f} °C, {hum:.0f} %RH")
        self.comfort_reasons = reasons if self.comfort.state == Comfort.OUT_OF_RANGE else []

    def _propose(self, region: _Region, candidate: enum.Enum, now: float, dwell: float,
                 reason: str) -> bool:
        old = region.state
        if region.propose(candidate, now, dwell):
            self._event(now, region.name, old.value, candidate.value, reason)
            return True
        return False

    def _force(self, region: _Region, state: enum.Enum, now: float, reason: str) -> None:
        self._propose(region, state, now, 0.0, reason)

    def _event(self, now: float, region: str, old: str, new: str, reason: str) -> None:
        event = Event(now, region, old, new, reason)
        self.events.append(event)
        self._pending.append(event)

    # ---- Outputs -------------------------------------------------------------

    def drain_events(self) -> list[Event]:
        """State changes since the last call, for the console."""
        events, self._pending = self._pending, []
        return events

    def state(self) -> dict:
        """JSON-ready summary for the dashboard."""
        return {
            "mode": self.mode.name,
            "activity": self.activity.state.value,
            "occupied": self.activity.state.occupied,
            "air": self.air.state.value,
            "comfort": self.comfort.state.value,
            "comfort_reasons": list(self.comfort_reasons),
            "confidence": round(self._confidence, 2),
            "zones": [{
                "zone": v.zone, "node_id": v.node_id, "stale": v.stale,
                "probs": [round(x) for x in v.probs] if v.probs else None,
                "motion_pct": None if v.motion_pct is None else round(v.motion_pct),
                "co2_ppm": v.co2_ppm,
            } for v in self._views],
        }


def format_event(e: Event) -> str:
    return f"{e.region}: {e.old} -> {e.new} ({e.reason})"


def _trim(items: deque, oldest: float) -> None:
    while items and items[0][0] < oldest:
        items.popleft()
