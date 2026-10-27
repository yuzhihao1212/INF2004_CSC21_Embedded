"""Plays every simulator scenario through the fusion engine in simulated time
and checks each phase ends in the state it promises. If a fusion threshold
changes so that a demo scenario no longer shows its state, this fails.

Run from the pc/ folder:  python -m unittest -v
"""

import unittest

from mosaic import protocol as p
from mosaic import scenarios
from mosaic.fusion import FusionEngine
from mosaic.simulator import Simulator

LECTURE = ("FOCUSED_LECTURE", "NORMAL", "COMFORTABLE")

# (activity, air, comfort) at the end of each phase
EXPECTED = {
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


def play(scenario: scenarios.Scenario, mode: p.Mode, seed: int) -> list[tuple[str, str, str]]:
    """State at the end of each phase, reporting once a second."""
    sim = Simulator(nodes=4, seed=seed, scenario=scenario)
    engine = FusionEngine()
    engine.set_mode(mode, 0.0)
    ends = []
    for t in range(int(scenario.seconds)):
        now = float(t)
        for data in sim.telemetry(now):
            header, telemetry = p.decode(data)
            engine.add(header.node_id, telemetry, now)
        engine.evaluate(now, online={1, 2, 3, 4})
        if sim.phase(now + 1)[0] != sim.phase(now)[0] or t == int(scenario.seconds) - 1:
            s = engine.state()
            ends.append((s["activity"], s["air"], s["comfort"]))
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


if __name__ == "__main__":
    unittest.main()
