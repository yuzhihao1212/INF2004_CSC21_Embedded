"""Lecturer-level comparison on the PC; no sockets, sleeps or Pico clock sync.

Window i is dated receive_time - (count - 1 - i) * 0.5 seconds. Independent
audio and report clocks can add up to 500 ms of batching delay, even with tiny
RTT. Unlike Darius's common-clock C API, receive time cannot align sample starts
or remove unequal processing/batching/transport delays. Strict per-window
pairing may therefore produce UNKNOWN/PENDING intermittently. Fusion smooths
the actual known window results; it must not count repeated evaluations as
extra windows. This is a level comparison, not echo cancellation.

The regression, nonnegative gain/background, nearest-rank 95th percentile,
20/64 pair limits and 25% + 4 ADC-count margin follow origin/darius's
firmware/audio/reference_detector.c. Protocol v2 has probabilities, not its
three context votes: speech evidence is 100 - background - transient. Missing
or invalid evidence produces UNKNOWN, never a negative speech observation.
Calibration is operator-controlled and frozen once fitted. Only baselines,
not timestamps, pending windows or TALKING state, are persisted.
"""

from __future__ import annotations

import enum
import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from mosaic import protocol as p

WINDOW_S = 0.5


class ReferenceState(enum.Enum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATING = "CALIBRATING"
    QUIET = "QUIET"
    PENDING = "PENDING"
    TALKING = "TALKING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReferenceConfig:
    pair_tolerance_s: float = 0.25
    max_age_s: float = 1.5
    max_gap_s: float = 0.75
    calibration_speech_pct: float = 60.0
    student_speech_pct: float = 60.0
    min_rms: float = 4.0
    min_pairs: int = 20
    max_pairs: int = 64
    relative_margin: float = 0.25
    absolute_margin: float = 4.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"reference {name} must be a finite number")
        if not 20 <= self.min_pairs <= self.max_pairs <= 64 or any(
                not isinstance(n, int) for n in (self.min_pairs, self.max_pairs)):
            raise ValueError("reference pair counts must be integers: 20 <= min <= max <= 64")
        if self.pair_tolerance_s < 0:
            raise ValueError("reference pairing tolerance must be nonnegative")
        if self.max_gap_s < WINDOW_S or self.max_age_s < WINDOW_S:
            raise ValueError("reference gap and age limits must be at least 0.5 s")
        if not all(0 <= x <= 100 for x in (self.calibration_speech_pct, self.student_speech_pct)):
            raise ValueError("reference speech thresholds must be percentages")
        if not 0 <= self.min_rms <= 4095 or min(self.relative_margin, self.absolute_margin) < 0:
            raise ValueError("reference RMS/margins must be nonnegative ADC levels")


@dataclass(frozen=True)
class _Window:
    time: float
    rms: float
    speech: float


@dataclass
class _Student:
    state: ReferenceState = ReferenceState.UNCALIBRATED
    calibrating: bool = False
    started: float = float("-inf")
    powers: list[tuple[float, float]] = field(default_factory=list)
    saved_pairs: int = 0
    gain: Optional[float] = None
    background_power: Optional[float] = None
    upper_residual: Optional[float] = None
    references: deque[_Window] = field(default_factory=deque)
    windows: deque[_Window] = field(default_factory=deque)
    last_pair: Optional[tuple[float, float]] = None
    positive: int = 0
    weak: int = 0
    hold: bool = False
    student_rms: Optional[float] = None
    expected_rms: Optional[float] = None
    threshold: Optional[float] = None
    reason: str = "Start lecturer-only calibration"
    results: list[tuple[float, ReferenceState]] = field(default_factory=list)


class ReferenceFusion:
    def __init__(self, zones: dict[int, str], reference_zone: Optional[str] = "A",
                 config: Optional[ReferenceConfig] = None) -> None:
        self.config = config or ReferenceConfig()
        self.zones = dict(zones)
        self.reference_zone = reference_zone
        matches = [node for node, zone in zones.items() if zone == reference_zone]
        self.reference_node = matches[0] if len(matches) == 1 else None
        self.students = {zone: _Student() for zone in zones.values() if zone != reference_zone}
        self._revisions = {zone: 0 for zone in self.students}
        # node -> newest audio sequence, estimated newest time, overrun counter
        self._streams: dict[int, tuple[int, float, int]] = {}

    @property
    def enabled(self) -> bool:
        return self.reference_node is not None

    def _targets(self, zone: Optional[str]) -> list[str]:
        if not self.enabled:
            raise ValueError("reference comparison is disabled or the reference zone is unmapped")
        if zone is not None and zone not in self.students:
            raise KeyError(zone)
        return [zone] if zone is not None else list(self.students)

    def calibrate(self, now: float, zone: Optional[str] = None) -> None:
        """Discard selected baselines and collect future lecturer-only pairs."""
        for name in self._targets(zone):
            self._revisions[name] += 1
            self.students[name] = _Student(state=ReferenceState.CALIBRATING,
                                           calibrating=True, started=now,
                                           reason="Keep students quiet while the lecturer speaks")

    def reset(self, zone: Optional[str] = None) -> None:
        """Discard selected baselines without starting calibration."""
        for name in self._targets(zone):
            self._revisions[name] += 1
            self.students[name] = _Student()

    @staticmethod
    def _unknown(student: _Student, reason: str) -> None:
        student.state, student.reason = ReferenceState.UNKNOWN, reason
        student.positive = student.weak = 0
        student.hold = False
        student.expected_rms = student.threshold = None
        student.last_pair = None

    def _invalidate(self, node_id: int, reason: str) -> None:
        affected = (self.students.values() if node_id == self.reference_node
                    else [self.students[self.zones[node_id]]])
        for student in affected:
            self._unknown(student, reason)
            student.references.clear()
            student.windows.clear()

    def add(self, node_id: int, telemetry: p.Telemetry, now: float, *, reboot: bool = False) -> None:
        """Queue each new window once, oldest first; pair in either arrival order.

        UNKNOWN class is not invalid if probabilities are usable. Protocol v2
        does not carry clipping flags; empty/malformed audio, changed overrun
        counters, sequence gaps/replays, time gaps and liveness are observable.
        Missing windows reset persistence but the available windows are still
        processed. Overruns and invalid/nonmonotonic reports are discarded.
        """
        if not self.enabled or node_id not in self.zones:
            return
        if not math.isfinite(now):
            raise ValueError("now must be finite monotonic seconds")
        if reboot:
            self._streams.pop(node_id, None)
            self._invalidate(node_id, "Node rebooted; confirm placement/gain before reuse")
        previous = self._streams.get(node_id)
        count = len(telemetry.audio)
        seq = telemetry.audio_window_seq
        if not 0 <= count <= p.AUDIO_WINDOWS_PER_REPORT or not 0 <= seq < 65536:
            self._invalidate(node_id, "Invalid audio window count or sequence")
            return
        delta = (seq - previous[0]) % 65536 if previous else count
        if previous and ((delta == 0 and count > 0) or delta >= 32768):
            self._invalidate(node_id, "Repeated or out-of-order audio")
            return
        self._streams[node_id] = (seq, now, telemetry.audio_overruns)
        if not count:
            self._invalidate(node_id, "No valid audio windows")
            return
        new_count = min(delta, count)
        first_time = now - (new_count - 1) * WINDOW_S
        if previous:
            if first_time <= previous[1] or telemetry.audio_overruns != previous[2]:
                self._invalidate(node_id, "Audio overrun or nonmonotonic receive time")
                return
            if delta > count or first_time - previous[1] > self.config.max_gap_s:
                affected = (self.students.values() if node_id == self.reference_node
                            else [self.students[self.zones[node_id]]])
                for student in affected:
                    self._unknown(student, "Audio gap; processing available windows")
                    # The other stream may already have this report's fresh
                    # windows. Clearing BOTH queues here would make every long
                    # report interval permanently unpairable, in either order.
                    (student.references if node_id == self.reference_node else student.windows).clear()
        windows = []
        for i, window in enumerate(telemetry.audio[-new_count:]):
            probs = window.prob_pct
            if (not math.isfinite(window.rms) or not 0 <= window.rms <= 4095
                    or len(probs) != p.AUDIO_CLASS_COUNT
                    or any(not math.isfinite(x) or not 0 <= x <= 100 for x in probs)
                    or not 0 < sum(probs) <= 100):
                self._invalidate(node_id, "Invalid RMS or class probabilities")
                return
            speech = 100 - probs[p.AudioClass.BACKGROUND_NOISE - 1] - probs[p.AudioClass.TRANSIENT_NOISE - 1]
            windows.append(_Window(first_time + i * WINDOW_S, window.rms, speech))
        affected = (self.students.values() if node_id == self.reference_node
                    else [self.students[self.zones[node_id]]])
        for student in affected:
            queue = student.references if node_id == self.reference_node else student.windows
            queue.extend(windows)
            self._pair(student, now)

    def _pair(self, student: _Student, now: float) -> None:
        cfg = self.config
        for queue in (student.references, student.windows):
            while queue and now - queue[0].time > cfg.max_age_s:
                queue.popleft()
                self._unknown(student, "Audio expired before pairing")
        while student.references and student.windows:
            ref, local = student.references[0], student.windows[0]
            delta = ref.time - local.time
            if abs(delta) > cfg.pair_tolerance_s + 1e-9:
                (student.references if delta < 0 else student.windows).popleft()
                self._unknown(student, "Unaligned audio windows")
                continue
            student.references.popleft()
            student.windows.popleft()
            if min(ref.time, local.time) < student.started:
                continue
            if student.last_pair and any(t - prev > cfg.max_gap_s or t <= prev
                                         for t, prev in zip((ref.time, local.time), student.last_pair)):
                self._unknown(student, "Gap between paired windows")
                continue
            student.last_pair = (ref.time, local.time)
            self._step(student, ref, local)
            student.results.append((local.time, student.state))

    def drain_results(self) -> dict[str, list[tuple[float, ReferenceState]]]:
        """Each paired window's result exactly once, including both batch entries."""
        out = {name: s.results for name, s in self.students.items()}
        for student in self.students.values():
            student.results = []
        return out

    def revision(self, zone: str) -> int:
        """Changes on operator reset/recalibration/load, invalidating fusion history."""
        return self._revisions[zone]

    def _fit(self, student: _Student) -> bool:
        pairs = student.powers
        n = len(pairs)
        mx = sum(x for x, _ in pairs) / n
        my = sum(y for _, y in pairs) / n
        variance = sum((x - mx) ** 2 for x, _ in pairs)
        if variance <= 1e-6 * mx * mx * n:
            return False
        gain = max(0.0, sum((x - mx) * (y - my) for x, y in pairs) / variance)
        background = my - gain * mx
        if background < 0:
            background = 0.0
            xx = sum(x * x for x, _ in pairs)
            gain = max(0.0, sum(x * y for x, y in pairs) / xx) if xx else 0.0
        residuals = sorted(max(0.0, y - (gain * x + background)) for x, y in pairs)
        student.gain, student.background_power = gain, background
        student.upper_residual = residuals[math.ceil(0.95 * n) - 1]
        return True

    def _step(self, student: _Student, ref: _Window, local: _Window) -> None:
        cfg = self.config
        student.student_rms = local.rms
        if student.gain is None:
            if not student.calibrating:
                student.state = ReferenceState.UNCALIBRATED
                return
            student.state = ReferenceState.CALIBRATING
            if ref.speech < cfg.calibration_speech_pct or ref.rms < cfg.min_rms:
                student.reason = "Waiting for lecturer speech"
                return
            if len(student.powers) < cfg.max_pairs:
                student.powers.append((ref.rms ** 2, local.rms ** 2))
            if len(student.powers) < cfg.min_pairs:
                return
            if not self._fit(student):
                student.reason = f"Calibration needs level variation; restart at {cfg.max_pairs} pairs"
                return
            student.calibrating = False
            student.state, student.reason = ReferenceState.QUIET, "Baseline ready"
            # Calibration itself never emits a talking event.
            self._levels(student, ref, local)
        else:
            strong = self._levels(student, ref, local) and local.speech >= cfg.student_speech_pct
            if local.rms < cfg.min_rms:  # C's LOW_LEVEL resets immediately, even during hold.
                student.positive = student.weak = 0
                student.state, student.hold = ReferenceState.QUIET, False
            elif strong:
                student.positive = min(2, student.positive + 1)
                student.weak = 0
                student.hold = False
                student.state = ReferenceState.TALKING if student.positive >= 2 else ReferenceState.PENDING
            elif student.state == ReferenceState.TALKING and student.weak == 0:
                student.weak, student.hold = 1, True
            else:
                student.positive = student.weak = 0
                student.state, student.hold = ReferenceState.QUIET, False
            student.reason = "Excess speech" if strong else "Within baseline or insufficient speech"

    def _levels(self, student: _Student, ref: _Window, local: _Window) -> bool:
        expected = student.gain * ref.rms ** 2 + student.background_power
        student.expected_rms = math.sqrt(max(0.0, expected))
        student.threshold = (math.sqrt(max(0.0, expected + student.upper_residual))
                             * (1 + self.config.relative_margin) + self.config.absolute_margin)
        return local.rms > student.threshold

    def evaluate(self, now: float, online: set[int]) -> None:
        """Expire persistence even without another packet. STALE is not ONLINE."""
        if not self.enabled:
            return
        for node, name in self.zones.items():
            if node == self.reference_node:
                continue
            student = self.students[name]
            if self.reference_node not in online or node not in online:
                self._unknown(student, "Reference or student node stale/offline")
                student.references.clear()
                student.windows.clear()
            elif student.last_pair and now - min(student.last_pair) > self.config.max_age_s:
                self._unknown(student, "Paired audio stale")
                student.references.clear()
                student.windows.clear()
            self._pair(student, now)

    def calibrated(self, zone: str) -> bool:
        return self.enabled and zone in self.students and self.students[zone].gain is not None

    def talking(self, zone: str) -> bool:
        return self.calibrated(zone) and self.students[zone].state == ReferenceState.TALKING

    def state(self) -> dict:
        return {"enabled": self.enabled, "zone": self.reference_zone,
                "zones": {name: {
                    "state": s.state.value, "pairs_collected": len(s.powers) or s.saved_pairs,
                    "required_pairs": self.config.min_pairs, "gain": s.gain,
                    "background_power": s.background_power, "upper_residual": s.upper_residual,
                    "threshold": s.threshold, "student_rms": s.student_rms,
                    "expected_rms": s.expected_rms, "hold": s.hold, "reason": s.reason,
                } for name, s in self.students.items()} if self.enabled else {}}

    def save(self, path: str | Path) -> None:
        """Save frozen baselines only; loading requires the same map/profile."""
        models = {zone: {key: status[key] for key in (
            "gain", "background_power", "upper_residual", "pairs_collected")}
                  for zone, status in self.state()["zones"].items() if status["gain"] is not None}
        Path(path).write_text(json.dumps({"version": 1, "reference_zone": self.reference_zone,
                                         "zones": self.zones, "profile": asdict(self.config),
                                         "models": models}, indent=2, allow_nan=False) + "\n")

    def load(self, path: str | Path) -> None:
        """Validate completely before replacing state. Never restore a live alert."""
        data = json.loads(Path(path).read_text())
        if (not isinstance(data, dict) or data.get("version") != 1
                or data.get("reference_zone") != self.reference_zone
                or data.get("zones") != {str(n): z for n, z in self.zones.items()}
                or data.get("profile") != asdict(self.config)
                or not isinstance(data.get("models"), dict)):
            raise ValueError("calibration file does not match the reference map/profile")
        loaded = {name: _Student() for name in self.students}
        for name, model in data["models"].items():
            if name not in loaded or not isinstance(model, dict):
                raise ValueError("invalid calibration zone")
            values = [model.get(k) for k in ("gain", "background_power", "upper_residual")]
            n = model.get("pairs_collected")
            if (any(isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) or v < 0 for v in values)
                    or type(n) is not int or not self.config.min_pairs <= n <= self.config.max_pairs):
                raise ValueError("invalid calibration coefficients or pair count")
            s = loaded[name]
            s.gain, s.background_power, s.upper_residual = values
            s.saved_pairs = n
            self._unknown(s, "Loaded baseline; waiting for fresh paired audio")
        self.students = loaded
        self._revisions = {zone: revision + 1 for zone, revision in self._revisions.items()}
        self._streams.clear()
