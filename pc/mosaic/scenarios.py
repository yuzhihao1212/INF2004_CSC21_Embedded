"""Scripted classroom scenarios for the node simulator.

Each scenario is a list of phases. A phase lasts some seconds and sets, per
zone, what the nodes should sense: the audio class mix, PIR motion, and the
CO2 / temperature / humidity the room drifts towards. Nodes 1-2 are the
front zones (lecturer area) and 3-4 the rear, as in FusionConfig.

    python -m mosaic.dashboard --scenario lecture
    python -m mosaic.simulator --scenario demo --nodes 4

Phase lengths allow for the fusion engine's smoothing and dwell times, so
each phase shows its intended classroom state before the next one starts.
The last phase holds once the scenario ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Audio class mix, % for (background, lecturer speech, student conversation, transient)
SILENT = (90, 4, 3, 3)
SPEECH = (8, 75, 12, 5)
CHAT = (8, 15, 72, 5)
SETTLING = (55, 20, 20, 5)  # People arriving: some voices, nothing dominant


@dataclass(frozen=True)
class Zone:
    probs: tuple[int, int, int, int] = SILENT
    pir_pct: int = 0
    co2_ppm: int = 550
    temperature_c: float = 24.0
    humidity_pct: float = 55.0


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
    """Phase zones for a lecture: speech at the front, seated students at the back."""
    front = Zone(SPEECH, pir_pct=25, co2_ppm=co2, temperature_c=temp, humidity_pct=humidity)
    rear = rear or Zone(SILENT, pir_pct=5, co2_ppm=co2, temperature_c=temp, humidity_pct=humidity)
    return dict(default=rear, zones={1: front, 2: front})


def _phase(seconds: float, label: str, expect: str, **zones) -> Phase:
    return Phase(seconds, label, expect, **zones)


EMPTY = _phase(40, "Empty classroom", "EMPTY", default=Zone())
LECTURE = _phase(120, "Lecturer teaching, students seated", "QUIET, then FOCUSED_LECTURE",
                 **_lecture())
REAR_CHATTER = _phase(200, "Rear students start chatting", "NOISE_RISING, then SUSTAINED_CHATTER",
                      **_lecture(co2=850, rear=Zone(CHAT, pir_pct=20, co2_ppm=850)))
SETTLED = _phase(90, "Class settles down", "FOCUSED_LECTURE", **_lecture())
CO2_BUILDS = _phase(180, "Door and windows closed: CO2 builds up", "air POOR_VENTILATION",
                    **_lecture(co2=1450))
WINDOW_OPEN = _phase(150, "Window opened", "air back to NORMAL", **_lecture(co2=650))
AIRCON_FAILS = _phase(180, "Air-conditioning fails", "comfort OUT_OF_RANGE (too warm, too humid)",
                      **_lecture(temp=30.0, humidity=75.0))
AIRCON_BACK = _phase(150, "Air-conditioning restored", "comfort back to COMFORTABLE",
                     **_lecture(temp=24.0, humidity=55.0))

SCENARIOS: dict[str, Scenario] = {
    "lecture": Scenario(
        "A lecture where the back rows start chatting, then settle.",
        (EMPTY, LECTURE, REAR_CHATTER, SETTLED)),
    "discussion": Scenario(
        "Lecture, then group work with every zone talking. In Lecture mode this is "
        "NOISE_RISING and SUSTAINED_CHATTER; click Discussion on the dashboard to see DISCUSSION.",
        (LECTURE,
         _phase(180, "Group work: every zone talking", "DISCUSSION in Discussion mode, "
                "otherwise NOISE_RISING", default=Zone(CHAT, pir_pct=30, co2_ppm=800)),
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
        (EMPTY, LECTURE, REAR_CHATTER, SETTLED, CO2_BUILDS, WINDOW_OPEN, AIRCON_FAILS,
         AIRCON_BACK)),
}


def get(name: Optional[str]) -> Optional[Scenario]:
    return SCENARIOS[name] if name else None
