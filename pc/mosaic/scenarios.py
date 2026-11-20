"""Scripted classroom scenarios for the node simulator.

Each scenario is a list of phases. A phase lasts some seconds and sets, per
zone, what the nodes should sense: the audio class mix, PIR motion, and the
CO2 / temperature / humidity the room drifts towards. Nodes 1-2 are the
front zones (node 1 is the lecturer) and 3-4 the rear, as in FusionConfig.

    python -m mosaic.dashboard --scenario lecture
    python -m mosaic.simulator --scenario demo --nodes 4

Phase lengths allow for the fusion engine's smoothing and dwell times, so
each phase shows its intended classroom state before the next one starts.
The last phase holds once the scenario ends.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

# Audio class mix, % for (background, speech, reserved, transient)
SILENT = (90, 7, 0, 3)
SPEECH = (8, 87, 0, 5)
SETTLING = (60, 35, 0, 5)  # People arriving: some voices, nothing dominant
ROWDY = (5, 75, 0, 20)     # Shouting over each other, chairs scraping

# ADC RMS levels: lecturer at node 1, the same voice heard further away, and
# students talking next to a node (louder there than the far-away lecturer).
LECTURER_RMS = 100
FRONT_BLEED_RMS = 60
REAR_BLEED_RMS = 35
STUDENT_TALK_RMS = 95
ROWDY_RMS = 220
# Stand-in for a loud level captured with a sound meter at each student node.
# Above talking (95, swinging up to about 119) and below rowdy (down to about 165).
SIM_LOUD_RMS = 150


@dataclass(frozen=True)
class Zone:
    probs: tuple[int, int, int, int] = SILENT
    pir_pct: int = 0
    co2_ppm: int = 550
    temperature_c: float = 24.0
    humidity_pct: float = 55.0
    rms: Optional[float] = None  # ADC RMS level; None preserves the random range.


@dataclass(frozen=True)
class Phase:
    seconds: float
    label: str
    expect: str        # What the dashboard should show, for the console
    default: Zone      # Zones not listed in `zones`
    zones: dict[int, Zone] = field(default_factory=dict)

    def zone(self, node_id: int) -> Zone:
        return self.zones.get(node_id, self.default)


@dataclass(frozen=True)
class Scenario:
    description: str
    phases: tuple[Phase, ...]

    @property
    def seconds(self) -> float:
        return sum(phase.seconds for phase in self.phases)

    def phase_at(self, elapsed: float) -> tuple[int, Phase]:
        """Index and phase at `elapsed` seconds; the last phase holds."""
        for index, phase in enumerate(self.phases):
            if elapsed < phase.seconds:
                return index, phase
            elapsed -= phase.seconds
        return len(self.phases) - 1, self.phases[-1]


def _lecture(co2: int = 750, temp: float = 24.0, humidity: float = 55.0,
             rear: Optional[Zone] = None) -> dict:
    """Phase zones for a lecture. As in a real room, every node hears the
    lecturer as SPEECH; only the level drops with distance (ADC RMS)."""
    env = dict(co2_ppm=co2, temperature_c=temp, humidity_pct=humidity)
    lecturer = Zone(SPEECH, pir_pct=25, rms=LECTURER_RMS, **env)
    front = Zone(SPEECH, pir_pct=5, rms=FRONT_BLEED_RMS, **env)
    seated = Zone(SPEECH, pir_pct=5, rms=REAR_BLEED_RMS, **env)
    return dict(default=rear or seated, zones={1: lecturer, 2: front})


def _phase(seconds: float, label: str, expect: str, **zones) -> Phase:
    return Phase(seconds, label, expect, **zones)


EMPTY = _phase(40, "Empty classroom", "EMPTY", default=Zone())
LECTURE = _phase(120, "Lecturer teaching, students seated", "QUIET, then FOCUSED_LECTURE",
                 **_lecture())
REAR_CHATTER = _phase(200, "Rear students start chatting", "NOISE_RISING, then SUSTAINED_CHATTER",
                      **_lecture(co2=850, rear=Zone(SPEECH, pir_pct=20, co2_ppm=850, rms=STUDENT_TALK_RMS)))
ROWDY_REAR = _phase(60, "Back rows get rowdy", "SUSTAINED_CHATTER; zones C and D LOUD (Excessive noise)",
                    **_lecture(co2=900, rear=Zone(ROWDY, pir_pct=40, co2_ppm=900, rms=ROWDY_RMS)))
SETTLED = _phase(90, "Class settles down", "FOCUSED_LECTURE", **_lecture())
CO2_BUILDS = _phase(180, "Door and windows closed: CO2 builds up", "air POOR_VENTILATION",
                    **_lecture(co2=1450))
WINDOW_OPEN = _phase(150, "Window opened", "air back to NORMAL", **_lecture(co2=650))
AIRCON_FAILS = _phase(180, "Air-conditioning fails", "comfort OUT_OF_RANGE (too warm, too humid)",
                      **_lecture(temp=30.0, humidity=75.0))
AIRCON_BACK = _phase(150, "Air-conditioning restored", "comfort back to COMFORTABLE",
                     **_lecture(temp=24.0, humidity=55.0))


def _reference_lecture(student_talking: bool = False) -> dict:
    # Identical speech-like probabilities throughout: only local levels differ.
    return dict(default=Zone(SPEECH, pir_pct=5, co2_ppm=750, rms=35), zones={
        1: Zone(SPEECH, pir_pct=25, co2_ppm=750, rms=100),
        2: Zone(SPEECH, pir_pct=5, co2_ppm=750, rms=65),
        3: Zone(SPEECH, pir_pct=5, co2_ppm=750, rms=95 if student_talking else 35),
        4: Zone(SPEECH, pir_pct=5, co2_ppm=750, rms=30),
    })

SCENARIOS: dict[str, Scenario] = {
    "reference": Scenario(
        "Click Calibrate during lecturer-only speech. High speech probabilities everywhere; "
        "only the rear level increase identifies additional student speech.",
        (_phase(60, "Lecturer-only calibration: click Calibrate; keep students quiet",
                "baseline ready, FOCUSED_LECTURE", **_reference_lecture()),
         _phase(90, "Lecture heard at attenuated levels at student desks",
                "FOCUSED_LECTURE, student zones QUIET", **_reference_lecture()),
         _phase(200, "Students near node 3 talk; speech probabilities unchanged",
                "NOISE_RISING, then SUSTAINED_CHATTER; zone C TALKING",
                **_reference_lecture(student_talking=True)),
         _phase(90, "Students stop; lecturer continues",
                "FOCUSED_LECTURE, student zones QUIET", **_reference_lecture()))),
    "lecture": Scenario(
        "A lecture where the back rows start chatting, then settle.",
        (EMPTY, LECTURE, REAR_CHATTER, SETTLED)),
    "discussion": Scenario(
        "Lecture, then group work with every zone talking. In Lecture mode this is "
        "NOISE_RISING and SUSTAINED_CHATTER; click Discussion on the dashboard to see DISCUSSION.",
        (LECTURE,
         _phase(180, "Group work: every zone talking", "DISCUSSION in Discussion mode, "
                "otherwise NOISE_RISING", default=Zone(SPEECH, pir_pct=30, co2_ppm=800, rms=STUDENT_TALK_RMS)),
         _phase(90, "Back to the lecture", "FOCUSED_LECTURE", **_lecture()))),
    "ventilation": Scenario(
        "CO2 builds up during a lecture until the window is opened.",
        (_phase(60, "Lecture starts", "FOCUSED_LECTURE, air NORMAL", **_lecture(co2=700)),
         CO2_BUILDS, WINDOW_OPEN)),
    "comfort": Scenario(
        "The air-conditioning fails during a lecture, then is fixed.",
        (_phase(60, "Lecture starts", "FOCUSED_LECTURE, comfort COMFORTABLE", **_lecture()),
         AIRCON_FAILS, AIRCON_BACK)),
    "exam": Scenario(
        "A silent exam: nobody moves or speaks, but the room stays occupied (PIR is "
        "motion, not presence; raised CO2 shows people are there).",
        (_phase(60, "Students arrive and sit down", "QUIET",
                default=Zone(SETTLING, pir_pct=40, co2_ppm=750)),
         _phase(300, "Silent exam", "stays QUIET, never EMPTY",
                default=Zone(SILENT, pir_pct=0, co2_ppm=950)))),
    "demo": Scenario(
        "Every state in one run, for a live demonstration.",
        (EMPTY, LECTURE, REAR_CHATTER, ROWDY_REAR, SETTLED, CO2_BUILDS, WINDOW_OPEN, AIRCON_FAILS,
         AIRCON_BACK)),
}


class ScriptClock:
    """Script time for a scenario, which a presenter can pause, skip and speed up.

    Only the script moves: nodes keep reporting on their own real-time clocks.
    The simulator thread and the dashboard share one clock, so the page shows
    exactly the phase the nodes are playing. Starts on the first call.
    """

    RATES = (1, 2, 4)

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._lock = threading.Lock()
        self._anchor: Optional[float] = None  # Real time of the last change
        self._offset = 0.0                    # Script seconds at that time
        self.rate = 1
        self.paused = False
        self.jumps = 0  # Counts skips, so the simulator can move the room to the new phase
        # Presenter's fresh-air fan (the dashboard's People view draws it). While it
        # runs the simulator pulls CO2 towards outdoor air, faster than the script.
        self.ventilation = False

    def _elapsed(self, now: float) -> float:
        if self._anchor is None:
            self._anchor = now
        # Times before the last change (a report stamped just before a skip) count as
        # that change, so they never land back in the phase that was skipped.
        if self.paused or now <= self._anchor:
            return self._offset
        return self._offset + (now - self._anchor) * self.rate

    def _rebase(self, now: float) -> None:
        self._offset, self._anchor = self._elapsed(now), now

    def start(self, now: float) -> None:
        with self._lock:
            self._elapsed(now)

    def elapsed(self, now: float) -> float:
        with self._lock:
            return self._elapsed(now)

    def phase(self, now: float) -> tuple[int, Phase]:
        return self.scenario.phase_at(self.elapsed(now))

    def set_paused(self, now: float, paused: bool) -> None:
        with self._lock:
            self._rebase(now)
            self.paused = paused

    def set_rate(self, now: float, rate: int) -> None:
        if rate not in self.RATES:
            raise ValueError(f"rate must be one of {self.RATES}")
        with self._lock:
            self._rebase(now)
            self.rate = rate

    def next_phase(self, now: float) -> bool:
        """Jump to the start of the next phase; False on the last phase."""
        with self._lock:
            index, _ = self.scenario.phase_at(self._elapsed(now))
            if index + 1 >= len(self.scenario.phases):
                return False
            self._offset = sum(ph.seconds for ph in self.scenario.phases[:index + 1])
            self._anchor = now
            self.jumps += 1
            return True

    def set_ventilation(self, on: bool) -> None:
        with self._lock:
            self.ventilation = on

    @property
    def drift_rate(self) -> int:
        """How many reports' worth of drift each report makes: the room keeps pace with the script."""
        return 1 if self.paused else self.rate


def sim_loud_levels(zones: dict[int, str], reference_zone: Optional[str]) -> dict[str, int]:
    """Loud levels (rms_x16) for simulated student zones, as if captured."""
    return {name: round(SIM_LOUD_RMS * 16) for name in zones.values() if name != reference_zone}


def get(name: Optional[str]) -> Optional[Scenario]:
    return SCENARIOS[name] if name else None
