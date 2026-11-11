"""Integer lecturer-reference comparison; no sockets or shared Pico clock.

Public now arguments are monotonic seconds, converted ONCE by seconds_to_ms;
FusionEngine uses the *_ms entry points to forward its already-converted time.
Window i is dated receive_ms - (count - 1 - i) * 500. Independent clocks can
add 500 ms of batching delay even with tiny RTT; strict pairing can therefore
produce UNKNOWN/PENDING. Fusion smooths actual known window results once each, treating PENDING as
positive level-plus-speech evidence as well as TALKING/HOLD. Raw two-window onset
is retained here for diagnostics; it is not an extra gate on the smoother.

All levels use raw Q12.4 rms_x16 (0..65535), powers use ADC^2 * 256, speech
uses integer percent, and learned gain is nonnegative Q16 (65536 = unity).
Least squares uses exact integer sums; coefficients round half away from zero,
then gain/background saturate at zero. Prediction truncates the Q16 product.
Python ints do not overflow. No roots are computed here, even for outputs;
dashboard.py alone converts powers to display RMS. Persistence/hold, variance
gate, nearest-rank percentile and default 25% + 4 ADC margin follow the float
baseline. Baseline JSON v2 stores integer coefficients only; v1 needs recalibration.
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

WINDOW_MS = 500
Q16 = 65536
MAX_RMS_X16 = 65535


def seconds_to_ms(now):
    """The ONLY floating boundary: caller monotonic seconds -> integer ms.

    Round half away from zero once per public call. Internal *_ms entry points
    let FusionEngine forward its already-converted timestamp without converting
    it twice. No sensor value or decision arithmetic passes this boundary.
    """
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("now must be finite monotonic seconds")
    magnitude = int(abs(now) * 1000 + 0.5)
    return -magnitude if now < 0 else magnitude


def round_ratio(numerator: int, denominator: int) -> int:
    """Exact rational rounding, ties away from zero; positive denominator."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    rounded = (abs(numerator) * 2 + denominator) // (2 * denominator)
    return -rounded if numerator < 0 else rounded


def clamp_int(value: int, low: int, high: int) -> int:
    """Clamp direct callers to wire bounds; reject decimal/bool inputs."""
    if type(value) is not int:
        raise ValueError("telemetry values must be integers")
    return min(high, max(low, value))


def require_ms(now_ms: int) -> None:
    """The explicit integer-clock API must never admit decimal timestamps."""
    if type(now_ms) is not int:
        raise ValueError("now_ms must be integer milliseconds")


class ReferenceState(enum.Enum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATING = "CALIBRATING"
    QUIET = "QUIET"
    PENDING = "PENDING"
    TALKING = "TALKING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReferenceConfig:
    pair_tolerance_ms: int = 250
    max_age_ms: int = 1500
    max_gap_ms: int = 750
    calibration_speech_pct: int = 60
    student_speech_pct: int = 60
    min_rms_x16: int = 64
    min_pairs: int = 20
    max_pairs: int = 64
    relative_margin_pct: int = 25
    abs_margin_x16: int = 64

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in asdict(self).values()):
            raise ValueError("reference settings must be integers")
        if not 20 <= self.min_pairs <= self.max_pairs <= 64:
            raise ValueError("reference pair counts: 20 <= min <= max <= 64")
        if self.pair_tolerance_ms < 0:
            raise ValueError("reference pairing tolerance must be nonnegative")
        if min(self.max_gap_ms, self.max_age_ms) < WINDOW_MS:
            raise ValueError("reference gap and age limits must be at least 500 ms")
        if not all(0 <= x <= 100 for x in (self.calibration_speech_pct, self.student_speech_pct)):
            raise ValueError("reference speech thresholds must be percentages")
        if (not 0 <= self.min_rms_x16 <= MAX_RMS_X16
                or not 0 <= self.abs_margin_x16 <= MAX_RMS_X16
                or not 0 <= self.relative_margin_pct <= 100):
            raise ValueError("reference margins must be valid integer ADC/percentage levels")


@dataclass(frozen=True)
class _Window:
    time_ms: int
    rms_x16: int
    speech_pct: int


@dataclass
class _Student:
    state: ReferenceState = ReferenceState.UNCALIBRATED
    calibrating: bool = False
    started_ms: Optional[int] = None
    powers: list[tuple[int, int]] = field(default_factory=list)
    saved_pairs: int = 0
    gain_q16: Optional[int] = None
    background_power_x256: Optional[int] = None
    upper_residual_x256: Optional[int] = None
    references: deque[_Window] = field(default_factory=deque)
    windows: deque[_Window] = field(default_factory=deque)
    last_pair: Optional[tuple[int, int]] = None
    positive: int = 0
    weak: int = 0
    hold: bool = False
    student_rms_x16: Optional[int] = None
    expected_power_x256: Optional[int] = None
    threshold_power_x256: Optional[int] = None
    reason: str = "Start lecturer-only calibration"
    results: list[tuple[int, ReferenceState]] = field(default_factory=list)


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
        # node -> newest audio sequence, estimated newest time_ms, overrun counter
        self._streams: dict[int, tuple[int, int, int]] = {}

    @property
    def enabled(self) -> bool:
        return self.reference_node is not None

    def _targets(self, zone: Optional[str]) -> list[str]:
        if not self.enabled:
            raise ValueError("reference comparison is disabled or the reference zone is unmapped")
        if zone is not None and zone not in self.students:
            raise KeyError(zone)
        return [zone] if zone is not None else list(self.students)

    def calibrate(self, now, zone: Optional[str] = None) -> None:
        self.calibrate_ms(seconds_to_ms(now), zone)

    def calibrate_ms(self, now_ms: int, zone: Optional[str] = None) -> None:
        """Discard selected baselines and collect future lecturer-only pairs."""
        require_ms(now_ms)
        for name in self._targets(zone):
            self._revisions[name] += 1
            self.students[name] = _Student(state=ReferenceState.CALIBRATING,
                                           calibrating=True, started_ms=now_ms,
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
        student.expected_power_x256 = student.threshold_power_x256 = None
        student.last_pair = None

    def _invalidate(self, node_id: int, reason: str) -> None:
        affected = (self.students.values() if node_id == self.reference_node
                    else [self.students[self.zones[node_id]]])
        for student in affected:
            self._unknown(student, reason)
            student.references.clear()
            student.windows.clear()

    def add(self, node_id: int, telemetry: p.Telemetry, now, *, reboot: bool = False) -> None:
        self.add_ms(node_id, telemetry, seconds_to_ms(now), reboot=reboot)

    def add_ms(self, node_id: int, telemetry: p.Telemetry, now_ms: int, *, reboot: bool = False) -> None:
        """Queue each new window once, oldest first; pair in either arrival order.

        UNKNOWN class is not invalid if probabilities are usable. Protocol v2
        does not carry clipping flags; empty/malformed audio, changed overrun
        counters, sequence gaps/replays, time gaps and liveness are observable.
        Missing windows reset persistence but the available windows are still
        processed. Overruns and invalid/nonmonotonic reports are discarded.
        """
        require_ms(now_ms)
        if not self.enabled or node_id not in self.zones:
            return
        if reboot:
            self._streams.pop(node_id, None)
            self._invalidate(node_id, "Node rebooted; confirm placement/gain before reuse")
        previous = self._streams.get(node_id)
        count = len(telemetry.audio)
        seq = telemetry.audio_window_seq
        if (not 0 <= count <= p.AUDIO_WINDOWS_PER_REPORT or type(seq) is not int
                or not 0 <= seq < 65536 or type(telemetry.audio_overruns) is not int
                or not 0 <= telemetry.audio_overruns <= 65535):
            self._invalidate(node_id, "Invalid audio window count or sequence")
            return
        delta = (seq - previous[0]) % 65536 if previous else count
        if previous and ((delta == 0 and count > 0) or delta >= 32768):
            self._invalidate(node_id, "Repeated or out-of-order audio")
            return
        self._streams[node_id] = (seq, now_ms, telemetry.audio_overruns)
        if not count:
            self._invalidate(node_id, "No valid audio windows")
            return
        new_count = min(delta, count)
        first_time = now_ms - (new_count - 1) * WINDOW_MS
        if previous:
            if first_time <= previous[1] or telemetry.audio_overruns != previous[2]:
                self._invalidate(node_id, "Audio overrun or nonmonotonic receive time")
                return
            if delta > count or first_time - previous[1] > self.config.max_gap_ms:
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
            if (type(window.rms_x16) is not int or not 0 <= window.rms_x16 <= MAX_RMS_X16
                    or len(probs) != p.AUDIO_CLASS_COUNT
                    or any(type(x) is not int or not 0 <= x <= 100 for x in probs)
                    or window.uses_reserved_class()
                    or not 0 < sum(probs) <= 100):
                self._invalidate(node_id, "Invalid RMS or class probabilities")
                return
            speech_pct = 100 - probs[p.AudioClass.BACKGROUND_NOISE - 1] - probs[p.AudioClass.TRANSIENT_NOISE - 1]
            windows.append(_Window(first_time + i * WINDOW_MS, window.rms_x16, speech_pct))
        affected = (self.students.values() if node_id == self.reference_node
                    else [self.students[self.zones[node_id]]])
        for student in affected:
            queue = student.references if node_id == self.reference_node else student.windows
            queue.extend(windows)
            self._pair(student, now_ms)

    def _pair(self, student: _Student, now_ms: int) -> None:
        cfg = self.config
        for queue in (student.references, student.windows):
            while queue and now_ms - queue[0].time_ms > cfg.max_age_ms:
                queue.popleft()
                self._unknown(student, "Audio expired before pairing")
        while student.references and student.windows:
            ref, local = student.references[0], student.windows[0]
            delta = ref.time_ms - local.time_ms
            if abs(delta) > cfg.pair_tolerance_ms:
                (student.references if delta < 0 else student.windows).popleft()
                self._unknown(student, "Unaligned audio windows")
                continue
            student.references.popleft()
            student.windows.popleft()
            if student.started_ms is not None and min(ref.time_ms, local.time_ms) < student.started_ms:
                continue
            if student.last_pair and any(t - prev > cfg.max_gap_ms or t <= prev
                                         for t, prev in zip((ref.time_ms, local.time_ms), student.last_pair)):
                self._unknown(student, "Gap between paired windows")
                continue
            student.last_pair = (ref.time_ms, local.time_ms)
            self._step(student, ref, local)
            student.results.append((local.time_ms, student.state))

    def drain_results(self) -> dict[str, list[tuple[int, ReferenceState]]]:
        """Each paired window's result exactly once, including both batch entries."""
        out = {name: s.results for name, s in self.students.items()}
        for student in self.students.values():
            student.results = []
        return out

    def revision(self, zone: str) -> int:
        """Changes on operator reset/recalibration/load, invalidating fusion history."""
        return self._revisions[zone]

    def _fit(self, student: _Student) -> bool:
        # x/y are power in (ADC * 16)^2 = ADC^2 * 256. Python ints
        # retain exact sums, covariance and variance with no overflow.
        pairs = student.powers
        n = len(pairs)
        sx, sy = sum(x for x, _ in pairs), sum(y for _, y in pairs)
        sxx = sum(x * x for x, _ in pairs)
        sxy = sum(x * y for x, y in pairs)
        denominator = n * sxx - sx * sx
        if denominator * 1000000 <= sx * sx:
            return False  # Same relative variance gate as the float baseline.
        numerator = max(0, n * sxy - sx * sy)
        intercept_num = sy * denominator - numerator * sx
        if intercept_num < 0:
            background = 0
            numerator, denominator = sxy, sxx  # Nonnegative through-origin refit.
        else:
            background = round_ratio(intercept_num, n * denominator)
        student.gain_q16 = max(0, round_ratio(numerator * Q16, denominator))
        student.background_power_x256 = max(0, background)
        residuals = sorted(max(0, y - ((student.gain_q16 * x >> 16) + background))
                           for x, y in pairs)
        student.upper_residual_x256 = residuals[(95 * n + 99) // 100 - 1]
        return True

    def _step(self, student: _Student, ref: _Window, local: _Window) -> None:
        cfg = self.config
        student.student_rms_x16 = local.rms_x16
        if student.gain_q16 is None:
            if not student.calibrating:
                student.state = ReferenceState.UNCALIBRATED
                return
            student.state = ReferenceState.CALIBRATING
            if ref.speech_pct < cfg.calibration_speech_pct or ref.rms_x16 < cfg.min_rms_x16:
                student.reason = "Waiting for lecturer speech_pct"
                return
            if len(student.powers) < cfg.max_pairs:
                student.powers.append((ref.rms_x16 ** 2, local.rms_x16 ** 2))
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
            strong = self._levels(student, ref, local) and local.speech_pct >= cfg.student_speech_pct
            if local.rms_x16 < cfg.min_rms_x16:  # C's LOW_LEVEL resets immediately, even during hold.
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
            student.reason = "Excess speech_pct" if strong else "Within baseline or insufficient speech_pct"

    def _levels(self, student: _Student, ref: _Window, local: _Window) -> bool:
        expected = ((student.gain_q16 * ref.rms_x16 ** 2) >> 16) + student.background_power_x256
        student.expected_power_x256 = expected
        student.threshold_power_x256 = expected + student.upper_residual_x256
        adjusted = local.rms_x16 - self.config.abs_margin_x16
        # Reduce the rational margin before squaring: 125/100 = 5/4,
        # so the default is adjusted^2 * 16 > power * 25. No square root.
        margin = 100 + self.config.relative_margin_pct
        common = math.gcd(margin, 100)
        numerator, denominator = margin // common, 100 // common
        return adjusted > 0 and adjusted ** 2 * denominator ** 2 > student.threshold_power_x256 * numerator ** 2

    def evaluate(self, now, online: set[int]) -> None:
        self.evaluate_ms(seconds_to_ms(now), online)

    def evaluate_ms(self, now_ms: int, online: set[int]) -> None:
        """Expire persistence even without another packet. STALE is not ONLINE."""
        require_ms(now_ms)
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
            elif student.last_pair and now_ms - min(student.last_pair) > self.config.max_age_ms:
                self._unknown(student, "Paired audio stale")
                student.references.clear()
                student.windows.clear()
            self._pair(student, now_ms)

    def calibrated(self, zone: str) -> bool:
        return self.enabled and zone in self.students and self.students[zone].gain_q16 is not None

    def talking(self, zone: str) -> bool:
        return self.calibrated(zone) and self.students[zone].state == ReferenceState.TALKING

    def state(self) -> dict:
        return {"enabled": self.enabled, "zone": self.reference_zone,
                "zones": {name: {
                    "state": s.state.value, "pairs_collected": len(s.powers) or s.saved_pairs,
                    "required_pairs": self.config.min_pairs, "gain_q16": s.gain_q16,
                    "background_power_x256": s.background_power_x256, "upper_residual_x256": s.upper_residual_x256,
                    "threshold_power_x256": s.threshold_power_x256, "student_rms_x16": s.student_rms_x16,
                    "expected_power_x256": s.expected_power_x256, "hold": s.hold, "reason": s.reason,
                } for name, s in self.students.items()} if self.enabled else {}}

    def save(self, path: str | Path) -> None:
        """Save frozen baselines only; loading requires the same map/profile."""
        models = {zone: {key: status[key] for key in (
            "gain_q16", "background_power_x256", "upper_residual_x256", "pairs_collected")}
                  for zone, status in self.state()["zones"].items() if status["gain_q16"] is not None}
        Path(path).write_text(json.dumps({"version": 2, "reference_zone": self.reference_zone,
                                         "zones": self.zones, "profile": asdict(self.config),
                                         "models": models}, indent=2, allow_nan=False) + "\n")

    def load(self, path: str | Path) -> None:
        """Validate completely before replacing state. Never restore a live alert."""
        data = json.loads(Path(path).read_text())
        if (not isinstance(data, dict) or data.get("version") != 2
                or data.get("reference_zone") != self.reference_zone
                or data.get("zones") != {str(n): z for n, z in self.zones.items()}
                or data.get("profile") != asdict(self.config)
                or not isinstance(data.get("models"), dict)):
            raise ValueError("calibration file does not match the reference map/profile")
        loaded = {name: _Student() for name in self.students}
        for name, model in data["models"].items():
            if name not in loaded or not isinstance(model, dict):
                raise ValueError("invalid calibration zone")
            values = [model.get(k) for k in ("gain_q16", "background_power_x256", "upper_residual_x256")]
            n = model.get("pairs_collected")
            if (any(type(v) is not int or v < 0 for v in values)
                    or type(n) is not int or not self.config.min_pairs <= n <= self.config.max_pairs):
                raise ValueError("invalid calibration coefficients or pair count")
            s = loaded[name]
            s.gain_q16, s.background_power_x256, s.upper_residual_x256 = values
            s.saved_pairs = n
            self._unknown(s, "Loaded baseline; waiting for fresh paired audio")
        self.students = loaded
        self._revisions = {zone: revision + 1 for zone, revision in self._revisions.items()}
        self._streams.clear()
