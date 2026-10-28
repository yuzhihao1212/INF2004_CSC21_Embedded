"""Plays every simulator scenario through the fusion engine in simulated time
with independent node clocks and receive jitter, and checks each phase ends
in the state it promises. If a fusion threshold
changes so that a demo scenario no longer shows its state, this fails.

Run from the pc/ folder:  python -m unittest -v
"""

import unittest
from itertools import accumulate

from mosaic import protocol as p
from mosaic import scenarios
from mosaic.fusion import FusionEngine
from mosaic.simulator import Simulator

LECTURE = ("FOCUSED_LECTURE", "NORMAL", "COMFORTABLE")

# (activity, air, comfort) at the end of each phase
EXPECTED = {
    ("reference", p.Mode.LECTURE): [
        LECTURE, LECTURE, ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"), LECTURE],
    ("lecture", p.Mode.LECTURE): [
        ("EMPTY", "NORMAL", "COMFORTABLE"), LECTURE,
        ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"), LECTURE],
    ("discussion", p.Mode.LECTURE): [
        LECTURE, ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"), LECTURE],
    ("discussion", p.Mode.DISCUSSION): [
        LECTURE, ("DISCUSSION", "NORMAL", "COMFORTABLE"), LECTURE],
    ("ventilation", p.Mode.LECTURE): [
        LECTURE, ("FOCUSED_LECTURE", "POOR_VENTILATION", "COMFORTABLE"), LECTURE],
    ("comfort", p.Mode.LECTURE): [
        LECTURE, ("FOCUSED_LECTURE", "NORMAL", "OUT_OF_RANGE"), LECTURE],
    ("exam", p.Mode.LECTURE): [
        ("QUIET", "NORMAL", "COMFORTABLE"), ("QUIET", "NORMAL", "COMFORTABLE")],
    ("demo", p.Mode.LECTURE): [
        ("EMPTY", "NORMAL", "COMFORTABLE"), LECTURE,
        ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"), LECTURE,
        ("FOCUSED_LECTURE", "POOR_VENTILATION", "COMFORTABLE"), LECTURE,
        ("FOCUSED_LECTURE", "NORMAL", "OUT_OF_RANGE"), LECTURE],
}


def play(scenario: scenarios.Scenario, mode: p.Mode, seed: int, *, aligned=False) -> list[tuple[str, str, str]]:
    """Phase-end states with independent clocks and exact PC delivery times."""
    sim = Simulator(nodes=4, seed=seed, scenario=scenario, aligned=aligned,
                    receive_jitter_s=0 if aligned else 0.08)
    engine = FusionEngine()
    if scenario is scenarios.SCENARIOS["reference"]:
        engine.calibrate(0.0)  # Operator starts phase (a); production never auto-learns.
    engine.set_mode(mode, 0.0)
    ends = []
    boundaries = {round(end * 10) - 1: i for i, end in enumerate(
        accumulate(phase.seconds for phase in scenario.phases))}
    for step in range(round(scenario.seconds * 10)):
        now = step / 10
        for received, data in sim.poll(now):
            header, telemetry = p.decode(data)
            engine.add(header.node_id, telemetry, received)
        engine.evaluate(now, online={1, 2, 3, 4})
        if step in boundaries:
            s = engine.state()
            ends.append((s["activity"], s["air"], s["comfort"]))
            if scenario is scenarios.SCENARIOS["reference"]:
                students = s["reference"]["zones"]
                assert all(z["gain"] is not None for z in students.values())
                assert students["C"]["smoothed_state"] == ("TALKING" if boundaries[step] == 2 else "QUIET")
    return ends


class Scenarios(unittest.TestCase):
    def test_every_scenario_is_checked(self):
        self.assertEqual({name for name, _ in EXPECTED}, set(scenarios.SCENARIOS))

    def test_each_phase_reaches_its_state(self):
        for (name, mode), expected in EXPECTED.items():
            for seed in (1, 2):  # Different noise, same outcome
                with self.subTest(scenario=name, mode=mode.name, seed=seed):
                    self.assertEqual(play(scenarios.SCENARIOS[name], mode, seed), expected)

    def test_last_phase_holds(self):
        scenario = scenarios.SCENARIOS["exam"]
        index, phase = scenario.phase_at(scenario.seconds + 1000)
        self.assertEqual((index, phase), (len(scenario.phases) - 1, scenario.phases[-1]))

    def test_aligned_reference_fixture_still_available(self):
        self.assertEqual(play(scenarios.SCENARIOS["reference"], p.Mode.LECTURE, 1, aligned=True),
                         EXPECTED["reference", p.Mode.LECTURE])


if __name__ == "__main__":
    unittest.main()
