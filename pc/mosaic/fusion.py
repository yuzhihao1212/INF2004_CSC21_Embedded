"""Integer MOSAIC fusion: independent classroom and per-zone statecharts.

Classroom Activity/Air/Comfort use smoothing, occupancy evidence, dwell and
hysteresis. PENDING counts as positive reference evidence. All decisions compare
integer sums and counts by cross multiplication; rounded means never feed back.
Public now arguments are seconds and pass ONCE through reference.seconds_to_ms.
Internal timestamps, histories and durations are integer ms. Sensors retain wire
units (percent, ppm, signed tenths C, tenths RH, Q12.4 ADC RMS); gain is Q16.
Python integers do not overflow. State outputs are integers; dashboard.py alone
creates human decimal values/roots. See docs/fusion_numeric_representation.md.

Speech is attributed by zone. The configured reference zone is the lecturer
zone: dominant SPEECH at or above lecturer_zone_speech_pct gives it LECTURER.
Other zones use known calibrated reference results (PENDING and TALKING/HOLD
are positive windows). When unknown (not calibrated), SPEECH above the
conversation threshold counts only if it is not lecturer bleed-through: while
the lecturer zone speaks, the zone's mean level must reach
uncalibrated_local_rms_pct of the lecturer zone's.
FOCUSED_LECTURE needs lecturer speech and no detected student talk. In Discussion
mode the widespread gate is the share of student zones with audio that are
talking. In other modes any student talk can raise NOISE_RISING and sustain it.
With no mapped reference zone, all zones are student zones and FOCUSED_LECTURE
is unavailable; without a lecturer location, speech cannot identify a lecture.

Per-zone activity (10 s configurable dwell): offline or no recent audio ->
NO_DATA immediately; then LOUD for a student zone with a loud level (below);
otherwise apply the zone's role above, then MOTION when motion meets
motion_min_pct, else STILL.
LOUD ("excessive noise"): the operator holds a steady sound at a target level
(e.g. read on a phone sound meter) next to a node and captures it; the mean
rms_x16 over loud_capture_ms becomes that zone's loud level. A student zone is
LOUD while at least loud_enter_pct of its audio windows in audio_smooth_ms are
at or above it (loud_exit_pct to leave), for any sound class. The lecturer zone
is excluded: the lecturer speaks right next to it. RMS is unweighted ADC level,
not dB(A). Zones without a loud level keep the rules above.
STILL means no detected local talking/lecturer evidence or motion: attenuated
lecturer speech at student desks does not imply local talking. Voice-only evidence
below these classification gates also maps to STILL, rather than inventing a
sixth activity state. STALE retains last usable evidence and is marked separately.
Per-zone air is GOOD below 800 ppm, FAIR below 1200, POOR otherwise; comfort uses
configured tenths bounds/hysteresis. Both use zone_dwell_ms, and invalid/offline
readings become UNKNOWN immediately. Classroom decisions are independent of zone
dwell. Every configured zone stays in state(), including offline/unseen zones.
"""

from __future__ import annotations

import enum
import json
import warnings
from collections import deque
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from mosaic import protocol as p
from mosaic.reference import (MAX_RMS_X16, ReferenceConfig, ReferenceFusion, ReferenceState,
                              WINDOW_MS, clamp_int, require_ms, round_ratio, seconds_to_ms)

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
    # node_id -> zone label. front_zones is accepted for legacy configs;
    # reference_zone alone assigns the lecturer role.
    zones: dict[int, str] = field(default_factory=lambda: {1: "A", 2: "B", 3: "C", 4: "D"})
    front_zones: tuple[str, ...] = ("A", "B")
    mode: p.Mode = p.Mode.LECTURE

    # PC lecturer-reference comparison; None disables it. No baseline is
    # learned until the operator explicitly starts calibration.
    reference_zone: Optional[str] = "A"
    reference_pair_tolerance_ms: int = 250
    reference_max_age_ms: int = 1500
    reference_max_gap_ms: int = 750
    reference_calibration_speech_pct: int = 60
    reference_student_speech_pct: int = 60
    reference_min_rms_x16: int = 64
    reference_min_pairs: int = 20
    reference_max_pairs: int = 64
    reference_relative_margin_pct: int = 25
    reference_abs_margin_x16: int = 64
    reference_talking_pct: int = 50
    reference_min_known_windows: int = 4

    audio_smooth_ms: int = 10000
    motion_window_ms: int = 60000
    motion_min_pct: int = 10
    voice_min_pct: int = 40
    co2_occupied_ppm: int = 800
    occupied_after_ms: int = 20000
    empty_after_ms: int = 600000
    lecturer_zone_speech_pct: int = 50
    # Without calibration, while the lecturer zone speaks, a student zone's
    # speech counts as local talking only if its mean level is at least this
    # percent of the lecturer zone's: quieter speech is lecturer bleed-through.
    uncalibrated_local_rms_pct: int = 75
    conversation_enter_pct: int = 40
    conversation_exit_pct: int = 25
    quiet_work_conversation_enter_pct: int = 25
    quiet_work_conversation_exit_pct: int = 15
    widespread_pct: int = 50
    activity_dwell_ms: int = 20000
    chatter_after_ms: int = 120000
    co2_poor_ppm: int = 1200
    co2_recovered_ppm: int = 1000
    air_dwell_ms: int = 60000
    temp_min_x10: int = 200
    temp_max_x10: int = 280
    humidity_min_x10: int = 300
    humidity_max_x10: int = 700
    temp_hysteresis_x10: int = 5
    humidity_hysteresis_x10: int = 30
    comfort_dwell_ms: int = 60000
    zone_dwell_ms: int = 10000
    zone_layout: Optional[dict[str, list[int]]] = None
    # Excessive noise: zone -> loud level (rms_x16), captured per node.
    loud_levels_x16: dict[str, int] = field(default_factory=dict)
    loud_enter_pct: int = 70
    loud_exit_pct: int = 50
    loud_capture_ms: int = 5000
    loud_capture_min_windows: int = 6

    def reference_settings(self) -> ReferenceConfig:
        return ReferenceConfig(**{f.name: vars(self)["reference_" + f.name]
                                  for f in fields(ReferenceConfig)})

    def __post_init__(self) -> None:
        if (not self.zones or any(type(node) is not int or not 1 <= node <= 8
                                 or not isinstance(name, str) or not name for node, name in self.zones.items())
                or len(set(self.zones.values())) != len(self.zones)):
            raise ValueError("zones require unique labels and integer node IDs 1..8")
        if self.reference_zone is not None and not isinstance(self.reference_zone, str):
            raise ValueError("reference_zone must be a zone name or null")
        self.reference_settings()
        for name, value in vars(self).items():
            if name in {'zones', 'front_zones', 'mode', 'reference_zone', 'zone_layout', 'loud_levels_x16'}:
                continue
            if type(value) is not int:
                raise ValueError(f"{name} must be an integer")
            if name.endswith('_ms') and value < 0:
                raise ValueError(f"{name} must be nonnegative")
            if (name.endswith('_pct') or name in {'motion_min_pct', 'voice_min_pct'}) and not 0 <= value <= 100:
                raise ValueError(f"{name} must be in 0..100")
            if name.endswith('_ppm') and not 0 <= value <= 65535:
                raise ValueError(f"{name} must be in 0..65535")
        if not 1 <= self.reference_talking_pct <= 100 or self.reference_min_known_windows < 1:
            raise ValueError("reference TALKING percent/minimum must be positive")
        if not 0 <= self.loud_exit_pct <= self.loud_enter_pct or self.loud_capture_min_windows < 1:
            raise ValueError("loud_exit_pct must not exceed loud_enter_pct; capture needs a window")
        if (not isinstance(self.loud_levels_x16, dict)
                or any(name not in self.zones.values() or type(level) is not int
                       or not 1 <= level <= MAX_RMS_X16 for name, level in self.loud_levels_x16.items())):
            raise ValueError("loud_levels_x16 maps configured zones to rms_x16 in 1..65535")
        self.loud_levels_x16 = dict(self.loud_levels_x16)
        if not -32768 <= self.temp_min_x10 <= self.temp_max_x10 <= 32767:
            raise ValueError("temperature bounds must fit signed wire tenths")
        if not 0 <= self.humidity_min_x10 <= self.humidity_max_x10 <= 1000:
            raise ValueError("humidity bounds must be in 0..1000 tenths")
        if (not 0 <= self.temp_hysteresis_x10 * 2 <= self.temp_max_x10 - self.temp_min_x10
                or not 0 <= self.humidity_hysteresis_x10 * 2 <= self.humidity_max_x10 - self.humidity_min_x10):
            raise ValueError("comfort hysteresis must fit inside its range")
        if self.zone_layout is None:
            # Display only: one band per zone from the front (row 0, the
            # lecturer's area) to the back. Columns split a band door/window side.
            self.zone_layout = {name: [i, 0] for i, name in enumerate(self.zones.values())}
        if not isinstance(self.zone_layout, dict) or set(self.zone_layout) != set(self.zones.values()):
            raise ValueError("zone_layout must place every configured zone exactly once")
        cells = []
        for cell in self.zone_layout.values():
            if (not isinstance(cell, (list, tuple)) or len(cell) != 2
                    or any(type(v) is not int or not 0 <= v <= 7 for v in cell)):
                raise ValueError("zone_layout cells must be [row, col] integers in 0..7")
            cells.append(tuple(cell))
        if len(set(cells)) != len(cells):
            raise ValueError("zone_layout cells must be unique")
        self.zone_layout = {name: list(cell) for name, cell in self.zone_layout.items()}

    @classmethod
    def from_json(cls, path: str | Path) -> FusionConfig:
        """Defaults overridden by the keys in a JSON object. Unknown keys
        are an error, so a typo doesn't silently keep the default."""
        data = json.loads(Path(path).read_text())
        if "lecture_speech_pct" in data:
            warnings.warn("lecture_speech_pct is deprecated; use lecturer_zone_speech_pct",
                          DeprecationWarning, stacklevel=2)
            data.setdefault("lecturer_zone_speech_pct", data.pop("lecture_speech_pct"))
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


class ZoneActivity(enum.Enum):
    NO_DATA = "NO_DATA"
    STILL = "STILL"
    MOTION = "MOTION"
    LECTURER = "LECTURER"
    TALKING = "TALKING"
    LOUD = "LOUD"            # Excessive noise: over the zone's captured loud level


class ZoneAir(enum.Enum):
    UNKNOWN = "UNKNOWN"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


@dataclass
class ZoneView:
    """Exact integer sums/counts; rounded means are output metrics only."""
    zone: str
    node_id: int
    prob_sums: tuple[int, ...]
    audio_count: int
    motion_sum: int
    motion_count: int
    co2_ppm: Optional[int]
    temperature_x10: Optional[int]
    humidity_x10: Optional[int]
    stale: bool
    rms_sum: int = 0  # Sum of rms_x16 over the same audio windows as prob_sums
    loud_count: int = 0  # Audio windows at or above the zone's loud level

    def prob_sum(self, audio_class: p.AudioClass) -> int:
        return self.prob_sums[audio_class - 1]

    def prob_at_least(self, audio_class: p.AudioClass, threshold_pct: int) -> bool:
        return self.audio_count > 0 and self.prob_sum(audio_class) >= threshold_pct * self.audio_count

    def voices(self, threshold_pct: int) -> bool:
        return self.prob_at_least(p.AudioClass.SPEECH, threshold_pct)

    def motion(self, threshold_pct: int) -> bool:
        return self.motion_count > 0 and self.motion_sum >= threshold_pct * self.motion_count


@dataclass
class Event:
    time_ms: int
    region: str
    old: str
    new: str
    reason: str


class _Zone:
    def __init__(self) -> None:
        self.audio: deque[tuple[int, tuple[int, ...], int]] = deque()
        self.reference: deque[tuple[int, bool]] = deque()
        self.reference_revision = -1
        self.motion: deque[tuple[int, int]] = deque()
        self.co2: Optional[int] = None
        self.temp_hum: Optional[tuple[int, int]] = None
        self.received = False
        self.report_interval_ms = 1000
        self.latest_audio_valid = False
        self.activity = _Region("zone_activity", ZoneActivity.NO_DATA)
        self.air = _Region("zone_air", ZoneAir.UNKNOWN)
        self.comfort = _Region("zone_comfort", Comfort.UNKNOWN)
        self.loud_capture_ms: Optional[int] = None  # Capture start, while capturing
        self.loud_error: Optional[str] = None       # Why the last capture failed


class _Region:
    """One statechart region: a change happens once the same candidate
    state has been proposed continuously for its dwell time."""

    def __init__(self, name: str, state: enum.Enum) -> None:
        self.name = name
        self.state = state
        self.since_ms = 0
        self._candidate: Optional[enum.Enum] = None
        self._candidate_since_ms = 0

    def propose(self, candidate: enum.Enum, now_ms: int, dwell_ms: int) -> bool:
        if candidate == self.state:
            self._candidate = None
            return False
        if candidate != self._candidate:
            self._candidate, self._candidate_since_ms = candidate, now_ms
        if now_ms - self._candidate_since_ms < dwell_ms:
            return False
        self.state, self.since_ms, self._candidate = candidate, now_ms, None
        return True


class FusionEngine:
    def __init__(self, config: Optional[FusionConfig] = None) -> None:
        self.config = config or FusionConfig()
        self.mode = self.config.mode
        self.reference = ReferenceFusion(self.config.zones, self.config.reference_zone,
                                         self.config.reference_settings())
        self._zones: dict[int, _Zone] = {n: _Zone() for n in self.config.zones}
        self.activity = _Region("activity", Activity.UNKNOWN)
        self.air = _Region("air", Air.UNKNOWN)
        self.comfort = _Region("comfort", Comfort.UNKNOWN)
        self.comfort_reasons: list[str] = []
        self.events: deque[Event] = deque(maxlen=EVENT_HISTORY)
        self._views: list[ZoneView] = []
        self._confidence_pct = 0
        self._pending: list[Event] = []  # New events since drain_events()
        self._now_ms = 0
        self._online: set[int] = set()

    # ---- Inputs ------------------------------------------------------------

    def add(self, node_id: int, t: p.Telemetry, now, *, reboot: bool = False,
            report_interval_ms: int = 1000) -> None:
        """Clock boundary: convert seconds once, then enter integer processing."""
        self.add_ms(node_id, t, seconds_to_ms(now), reboot=reboot, report_interval_ms=report_interval_ms)

    def add_ms(self, node_id: int, t: p.Telemetry, now_ms: int, *, reboot: bool = False,
               report_interval_ms: int = 1000) -> None:
        """Record one TELEMETRY. Nodes not in config.zones are ignored."""
        require_ms(now_ms)
        if node_id not in self.config.zones:
            return
        if type(report_interval_ms) is not int or not 200 <= report_interval_ms <= 10000:
            raise ValueError("report_interval_ms must be a protocol interval in 200..10000")
        self.reference.add_ms(node_id, t, now_ms, reboot=reboot)
        zone = self._zones[node_id]
        zone.received = True
        zone.report_interval_ms = report_interval_ms
        zone.latest_audio_valid = False
        for window in t.audio:
            if (len(window.prob_pct) == p.AUDIO_CLASS_COUNT
                    and all(type(x) is int and 0 <= x <= 100 for x in window.prob_pct)
                    and not window.uses_reserved_class()
                    and 0 < sum(window.prob_pct) <= 100):
                zone.audio.append((now_ms, window.prob_pct, window.rms_x16))
                zone.latest_audio_valid = True
        if p.Valid.PIR in t.valid_flags:
            zone.motion.append((now_ms, clamp_int(t.pir_active_pct, 0, 100)))
        # Invalid readings clear the value: never fuse a stale or warming-up value.
        zone.co2 = clamp_int(t.co2_ppm, 0, 65535) if p.Valid.CO2 in t.valid_flags else None
        zone.temp_hum = ((clamp_int(t.temperature_x10, -32768, 32767), clamp_int(t.humidity_x10, 0, 1000))
                         if p.Valid.TEMP_HUM in t.valid_flags else None)
        self._collect_reference_results()

    def _collect_reference_results(self) -> None:
        results = self.reference.drain_results()
        known = (ReferenceState.QUIET, ReferenceState.PENDING, ReferenceState.TALKING)
        for node, name in self.config.zones.items():
            if name not in results or node not in self._zones:
                continue
            zone = self._zones[node]
            revision = self.reference.revision(name)
            if revision != zone.reference_revision:
                zone.reference.clear()
                zone.reference_revision = revision
            for time_ms, state in results[name]:
                if state in known:
                    zone.reference.append((time_ms, state in (ReferenceState.PENDING, ReferenceState.TALKING)))

    def _reference_summary(self, node: int) -> dict:
        cfg = self.config
        zone = self._zones[node]
        _trim(zone.reference, self._now_ms - cfg.audio_smooth_ms)
        count = len(zone.reference)
        talking = sum(value for _, value in zone.reference)
        reference_node = self.reference.reference_node
        reference_interval_ms = (self._zones[reference_node].report_interval_ms
                                 if reference_node in self._zones else 1000)
        # The paired student window may be the older entry in a batch. Allow
        # one configured report interval, its 500 ms batching age, and pairing
        # tolerance for receive jitter. A fixed 1500 ms cutoff interrupts every
        # 2000 ms report stream even when both nodes are online and healthy.
        freshness_ms = max(cfg.reference_max_age_ms,
                           max(zone.report_interval_ms, reference_interval_ms)
                           + WINDOW_MS + cfg.reference_pair_tolerance_ms)
        # Brief UNKNOWN window results are excluded, not negative votes. The
        # ROLLING result is UNKNOWN when evidence is insufficient/expired or a
        # node is unavailable; only then do activity rules use probabilities.
        available = (self.reference.calibrated(cfg.zones[node])
                     and node in self._online and self.reference.reference_node in self._online
                     and count >= cfg.reference_min_known_windows
                     and self._now_ms - zone.reference[-1][0] <= freshness_ms)
        state = ("TALKING" if talking * 100 >= cfg.reference_talking_pct * count else "QUIET") if available else "UNKNOWN"
        return {"smoothed_state": state, "talking_pct": round_ratio(talking * 100, count) if count else None,
                "known_windows": count, "required_known_windows": cfg.reference_min_known_windows,
                "talking_threshold_pct": cfg.reference_talking_pct,
                "freshness_ms": freshness_ms,
                "decision_source": "reference" if available else "probabilities"}

    def set_mode(self, mode: p.Mode, now) -> None:
        now_ms = seconds_to_ms(now)
        if mode != self.mode:
            self._event(now_ms, "mode", self.mode.name, mode.name, "operator")
            self.mode = mode

    def calibrate(self, now, zone: Optional[str] = None) -> None:
        """Start/restart lecturer-only calibration for all students or one zone."""
        self.reference.calibrate_ms(seconds_to_ms(now), zone)

    def reset_reference(self, zone: Optional[str] = None) -> None:
        self.reference.reset(zone)

    def _student_node(self, zone: str) -> int:
        node = next((n for n, name in self.config.zones.items() if name == zone), None)
        if node is None or zone == self.config.reference_zone:
            raise KeyError(zone)
        return node

    def capture_loud(self, now, zone: str) -> None:
        """Start capturing a student zone's loud level: the mean rms_x16 of the
        audio windows received in the next loud_capture_ms. KeyError if the
        zone is unknown or is the lecturer zone."""
        node = self._student_node(zone)
        self._zones[node].loud_capture_ms = seconds_to_ms(now)
        self._zones[node].loud_error = None

    def clear_loud(self, zone: str) -> None:
        node = self._student_node(zone)
        self.config.loud_levels_x16.pop(zone, None)
        self._zones[node].loud_capture_ms = None
        self._zones[node].loud_error = None

    def _finish_loud_captures(self, now_ms: int) -> None:
        cfg = self.config
        for node, zone in self._zones.items():
            start = zone.loud_capture_ms
            if start is None or now_ms - start < cfg.loud_capture_ms:
                continue
            zone.loud_capture_ms = None
            levels = [rms for t, _, rms in zone.audio if start < t <= start + cfg.loud_capture_ms]
            if len(levels) < cfg.loud_capture_min_windows:
                zone.loud_error = "not enough sound readings; is the sensor online?"
            elif sum(levels) < cfg.reference_min_rms_x16 * len(levels):
                zone.loud_error = "too quiet to be a loud level"
            else:
                cfg.loud_levels_x16[cfg.zones[node]] = max(1, round_ratio(sum(levels), len(levels)))
                zone.loud_error = None

    # ---- Evaluation ----------------------------------------------------------

    def evaluate(self, now, online: set[int], stale: set[int] = frozenset()) -> None:
        self.evaluate_ms(seconds_to_ms(now), online, stale)

    def evaluate_ms(self, now_ms: int, online: set[int], stale: set[int] = frozenset()) -> None:
        """Re-run the rules. `online` and `stale` are the node IDs the gateway
        reports in those states; OFFLINE nodes are simply absent."""
        require_ms(now_ms)
        cfg = self.config
        self._now_ms, self._online = now_ms, set(online - stale)
        self.reference.evaluate_ms(now_ms, online - stale)
        self._collect_reference_results()
        self._finish_loud_captures(now_ms)
        self._views = [self._view(node_id, now_ms, node_id in stale)
                       for node_id in sorted(self._zones)
                       if self._zones[node_id].received and (node_id in online or node_id in stale)]
        fresh = len(self._views) - sum(v.stale for v in self._views)
        # A STALE zone counts half: its data is up to 10 s old.
        self._confidence_pct = round_ratio(100 * fresh + 50 * (len(self._views) - fresh), len(cfg.zones))
        self._step_activity(now_ms)
        self._step_air(now_ms)
        self._step_comfort(now_ms)
        self._step_zones(now_ms, online, stale)

    def _view(self, node_id: int, now_ms: int, stale: bool) -> ZoneView:
        cfg, zone = self.config, self._zones[node_id]
        _trim(zone.audio, now_ms - cfg.audio_smooth_ms)
        _trim(zone.motion, now_ms - cfg.motion_window_ms)
        sums = tuple(sum(w[1][i] for w in zone.audio) for i in range(p.AUDIO_CLASS_COUNT))
        temp, hum = zone.temp_hum or (None, None)
        level = cfg.loud_levels_x16.get(cfg.zones[node_id])
        return ZoneView(cfg.zones[node_id], node_id, sums, len(zone.audio),
                        sum(m for _, m in zone.motion), len(zone.motion), zone.co2, temp, hum, stale,
                        sum(w[2] for w in zone.audio),
                        sum(w[2] >= level for w in zone.audio) if level is not None else 0)

    def _step_activity(self, now_ms: int) -> None:
        cfg, views = self.config, self._views
        if not views:
            self._force(self.activity, Activity.UNKNOWN, now_ms, "no zone data")
            return
        state = self.activity.state

        evidence = []
        for v in views:
            if v.motion(cfg.motion_min_pct):
                evidence.append(f"motion in {v.zone}")
            if v.voices(cfg.voice_min_pct):
                evidence.append(f"voices in {v.zone}")
        # CO2 only keeps the room occupied; it lags too much to declare it so.
        if state.occupied and any(v.co2_ppm and v.co2_ppm >= cfg.co2_occupied_ppm for v in views):
            evidence.append("raised CO2")

        if not evidence:
            dwell = cfg.empty_after_ms if state.occupied else cfg.occupied_after_ms
            self._propose(self.activity, Activity.EMPTY, now_ms, dwell, "no motion, voices or raised CO2")
            return
        if not state.occupied:
            self._propose(self.activity, Activity.QUIET, now_ms, cfg.occupied_after_ms,
                          ", ".join(evidence))
            return

        candidate, reason = self._occupied_candidate(state, now_ms)
        dwell = 0 if candidate == Activity.SUSTAINED_CHATTER else cfg.activity_dwell_ms
        self._propose(self.activity, candidate, now_ms, dwell, reason)

    def _occupied_candidate(self, state: Activity, now_ms: int) -> tuple[Activity, str]:
        cfg, views = self.config, self._views
        threshold = self._conversation_threshold(state in _NOISY)
        audio_views = [v for v in views if v.audio_count]
        students = [v for v in audio_views if v.zone != cfg.reference_zone]
        talking = [v.zone for v in students if self._student_talking(v, threshold)]
        widespread = bool(talking) and len(talking) * 100 >= cfg.widespread_pct * len(students)

        if self.mode == p.Mode.DISCUSSION:
            if widespread:
                return Activity.DISCUSSION, f"conversation in {', '.join(talking)}"
        elif talking:
            reason = f"conversation in {', '.join(talking)}"
            if state == Activity.SUSTAINED_CHATTER:
                return Activity.SUSTAINED_CHATTER, reason
            if state == Activity.NOISE_RISING and now_ms - self.activity.since_ms >= cfg.chatter_after_ms:
                return Activity.SUSTAINED_CHATTER, f"{reason} for {cfg.chatter_after_ms} ms"
            return Activity.NOISE_RISING, reason

        if not talking:
            for view in audio_views:
                if self._lecturer_speaking(view):
                    return Activity.FOCUSED_LECTURE, f"lecturer speech in {view.zone}"
        return Activity.QUIET, "no dominant activity"

    def _step_air(self, now_ms: int) -> None:
        cfg = self.config
        readings = [(v.co2_ppm, v.zone) for v in self._views if v.co2_ppm is not None]
        if not readings:
            self._force(self.air, Air.UNKNOWN, now_ms, "no valid CO2 reading")
            return
        ppm, zone = max(readings)
        if self.air.state == Air.POOR_VENTILATION:
            candidate = Air.NORMAL if ppm < cfg.co2_recovered_ppm else Air.POOR_VENTILATION
        else:
            candidate = Air.POOR_VENTILATION if ppm >= cfg.co2_poor_ppm else Air.NORMAL
        dwell = 0 if self.air.state == Air.UNKNOWN else cfg.air_dwell_ms
        self._propose(self.air, candidate, now_ms, dwell, f"CO2 {ppm} ppm in {zone}")

    def _comfort_reasons(self, temp_sum: int, hum_sum: int, count: int,
                         previous: Comfort) -> list[str]:
        cfg = self.config
        mt = cfg.temp_hysteresis_x10 if previous == Comfort.OUT_OF_RANGE else 0
        mh = cfg.humidity_hysteresis_x10 if previous == Comfort.OUT_OF_RANGE else 0
        tests = ((temp_sum > (cfg.temp_max_x10 - mt) * count, "too warm"),
                 (temp_sum < (cfg.temp_min_x10 + mt) * count, "too cold"),
                 (hum_sum > (cfg.humidity_max_x10 - mh) * count, "too humid"),
                 (hum_sum < (cfg.humidity_min_x10 + mh) * count, "too dry"))
        return [reason for test, reason in tests if test]

    def _step_comfort(self, now_ms: int) -> None:
        readings = [(v.temperature_x10, v.humidity_x10) for v in self._views
                    if v.temperature_x10 is not None]
        if not readings:
            self.comfort_reasons = []
            self._force(self.comfort, Comfort.UNKNOWN, now_ms, "no valid temperature reading")
            return
        reasons = self._comfort_reasons(sum(t for t, _ in readings), sum(h for _, h in readings),
                                        len(readings), self.comfort.state)
        candidate = Comfort.OUT_OF_RANGE if reasons else Comfort.COMFORTABLE
        dwell = 0 if self.comfort.state == Comfort.UNKNOWN else self.config.comfort_dwell_ms
        self._propose(self.comfort, candidate, now_ms, dwell,
                      "; ".join(reasons) or "temperature/humidity within range")
        self.comfort_reasons = reasons if self.comfort.state == Comfort.OUT_OF_RANGE else []

    def _conversation_threshold(self, noisy: bool) -> int:
        cfg = self.config
        if self.mode == p.Mode.QUIET_WORK:
            return cfg.quiet_work_conversation_exit_pct if noisy else cfg.quiet_work_conversation_enter_pct
        return cfg.conversation_exit_pct if noisy else cfg.conversation_enter_pct

    def _lecturer_speaking(self, view: ZoneView) -> bool:
        return (view.zone == self.config.reference_zone
                and view.voices(self.config.lecturer_zone_speech_pct)
                and view.prob_sum(p.AudioClass.SPEECH) == max(view.prob_sums))

    def _student_talking(self, view: ZoneView, threshold_pct: int) -> bool:
        reference = self._reference_summary(view.node_id)["smoothed_state"]
        if reference != "UNKNOWN":
            return reference == "TALKING"
        return view.voices(threshold_pct) and not self._lecturer_bleed(view)

    def _lecturer_bleed(self, view: ZoneView) -> bool:
        """Uncalibrated fallback: while the lecturer zone speaks, speech that is
        quieter here than uncalibrated_local_rms_pct of the lecturer zone's level
        is attributed to the lecturer. Compares mean levels by cross-multiplying."""
        lecturer = next((v for v in self._views if self._lecturer_speaking(v)), None)
        if lecturer is None or not view.audio_count:
            return False
        return (view.rms_sum * 100 * lecturer.audio_count
                < self.config.uncalibrated_local_rms_pct * lecturer.rms_sum * view.audio_count)

    def _loud(self, view: ZoneView, previous: ZoneActivity) -> bool:
        """Any sound class counts. Cross-multiplied share of windows over the level."""
        cfg = self.config
        if view.zone == cfg.reference_zone or view.zone not in cfg.loud_levels_x16:
            return False
        pct = cfg.loud_exit_pct if previous == ZoneActivity.LOUD else cfg.loud_enter_pct
        return view.loud_count * 100 >= pct * view.audio_count

    def _zone_candidate(self, view: ZoneView, previous: ZoneActivity) -> ZoneActivity:
        if not view.audio_count:
            return ZoneActivity.NO_DATA
        if self._loud(view, previous):
            return ZoneActivity.LOUD
        if self._lecturer_speaking(view):
            return ZoneActivity.LECTURER
        if view.zone != self.config.reference_zone:
            threshold = self._conversation_threshold(previous == ZoneActivity.TALKING)
            if self._student_talking(view, threshold):
                return ZoneActivity.TALKING
        return ZoneActivity.MOTION if view.motion(self.config.motion_min_pct) else ZoneActivity.STILL

    def _step_zones(self, now_ms: int, online: set[int], stale: set[int]) -> None:
        for node, zone in self._zones.items():
            if not zone.received or node not in online | stale:
                zone.activity.propose(ZoneActivity.NO_DATA, now_ms, 0)
                zone.air.propose(ZoneAir.UNKNOWN, now_ms, 0)
                zone.comfort.propose(Comfort.UNKNOWN, now_ms, 0)
                continue
            view = self._view(node, now_ms, node in stale)
            activity = (self._zone_candidate(view, zone.activity.state)
                        if zone.latest_audio_valid else ZoneActivity.NO_DATA)
            zone.activity.propose(activity, now_ms, 0 if activity == ZoneActivity.NO_DATA else self.config.zone_dwell_ms)
            ppm = view.co2_ppm
            air = (ZoneAir.UNKNOWN if ppm is None else ZoneAir.GOOD if ppm < 800
                   else ZoneAir.FAIR if ppm < 1200 else ZoneAir.POOR)
            zone.air.propose(air, now_ms, 0 if air == ZoneAir.UNKNOWN else self.config.zone_dwell_ms)
            if view.temperature_x10 is None:
                comfort = Comfort.UNKNOWN
            else:
                reasons = self._comfort_reasons(view.temperature_x10, view.humidity_x10, 1, zone.comfort.state)
                comfort = Comfort.OUT_OF_RANGE if reasons else Comfort.COMFORTABLE
            zone.comfort.propose(comfort, now_ms, 0 if comfort == Comfort.UNKNOWN else self.config.zone_dwell_ms)

    def _propose(self, region: _Region, candidate: enum.Enum, now_ms: int, dwell_ms: int,
                 reason: str) -> bool:
        old = region.state
        if region.propose(candidate, now_ms, dwell_ms):
            self._event(now_ms, region.name, old.value, candidate.value, reason)
            return True
        return False

    def _force(self, region: _Region, state: enum.Enum, now_ms: int, reason: str) -> None:
        self._propose(region, state, now_ms, 0, reason)

    def _event(self, now_ms: int, region: str, old: str, new: str, reason: str) -> None:
        event = Event(now_ms, region, old, new, reason)
        self.events.append(event)
        self._pending.append(event)

    # ---- Outputs -------------------------------------------------------------

    def drain_events(self) -> list[Event]:
        """State changes since_ms the last call, for the console."""
        events, self._pending = self._pending, []
        return events

    def state(self) -> dict:
        """JSON-ready summary for the dashboard."""
        reference = self.reference.state()
        for node, name in self.config.zones.items():
            if name in reference["zones"] and node in self._zones:
                reference["zones"][name].update(self._reference_summary(node))
        return {
            "now_ms": self._now_ms,
            "mode": self.mode.name,
            "activity": self.activity.state.value,
            "activity_since_ms": self.activity.since_ms,
            "air_since_ms": self.air.since_ms,
            "occupied": self.activity.state.occupied,
            "air": self.air.state.value,
            "comfort": self.comfort.state.value,
            "comfort_reasons": list(self.comfort_reasons),
            "confidence_pct": self._confidence_pct,
            "reference": reference,
            "zone_layout": self.config.zone_layout,
            "zones": [self._zone_output(node, reference) for node in sorted(self._zones)],
        }

    def _zone_output(self, node: int, reference: dict) -> dict:
        zone = self._zones[node]
        view = self._view(node, self._now_ms, node not in self._online)
        active = next((v for v in self._views if v.node_id == node), None)
        status = 'OFFLINE' if active is None else 'STALE' if active.stale else 'ONLINE'
        return {
            'zone': view.zone, 'node_id': node, 'status': status, 'stale': status == 'STALE',
            'state': zone.activity.state.value, 'since_ms': zone.activity.since_ms,
            'air': zone.air.state.value, 'comfort': zone.comfort.state.value,
            'layout': self.config.zone_layout[view.zone],
            'reference_zone': view.zone == self.config.reference_zone,
            'report_interval_ms': zone.report_interval_ms,
            'probs_pct': [round_ratio(x, view.audio_count) for x in view.prob_sums]
                         if active and view.audio_count else None,
            'motion_active': view.motion(self.config.motion_min_pct) if active and view.motion_count else None,
            'motion_pct': round_ratio(view.motion_sum, view.motion_count) if active and view.motion_count else None,
            'co2_ppm': view.co2_ppm if active else None,
            'temperature_x10': view.temperature_x10 if active else None,
            'humidity_x10': view.humidity_x10 if active else None,
            'reference': reference['zones'].get(view.zone),
            'loud': self._loud_output(node, view),
        }

    def _loud_output(self, node: int, view: ZoneView) -> Optional[dict]:
        """None for the lecturer zone: it never reports LOUD."""
        cfg, zone = self.config, self._zones[node]
        if view.zone == cfg.reference_zone:
            return None
        capturing = zone.loud_capture_ms is not None
        return {"level_x16": cfg.loud_levels_x16.get(view.zone),
                "capturing": capturing,
                "capture_left_ms": (max(0, zone.loud_capture_ms + cfg.loud_capture_ms - self._now_ms)
                                    if capturing else None),
                "error": zone.loud_error,
                "loud_pct": round_ratio(view.loud_count * 100, view.audio_count)
                            if view.zone in cfg.loud_levels_x16 and view.audio_count else None,
                "enter_pct": cfg.loud_enter_pct}



def format_event(e: Event) -> str:
    return f"{e.region}: {e.old} -> {e.new} ({e.reason})"


def _trim(items: deque, oldest_ms: int) -> None:
    while items and items[0][0] < oldest_ms:
        items.popleft()
