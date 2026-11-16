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
from mosaic.fusion import FusionConfig, FusionEngine
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
        ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"), ("SUSTAINED_CHATTER", "NORMAL", "COMFORTABLE"),
        LECTURE, ("FOCUSED_LECTURE", "POOR_VENTILATION", "COMFORTABLE"), LECTURE,
        ("FOCUSED_LECTURE", "NORMAL", "OUT_OF_RANGE"), LECTURE],
}

# Zone activity is independent of classroom dwell. Rear lecture bleed-through
# stays STILL after calibration; identical class probabilities cannot make it TALKING.
EXPECTED_ZONES = {
    'reference': [{'A': 'LECTURER', 'C': 'STILL'}, {'C': 'STILL'},
                  {'C': 'TALKING'}, {'C': 'STILL'}],
    'lecture': [{'A': 'STILL', 'C': 'STILL'}, {'A': 'LECTURER', 'C': 'STILL'},
                {'A': 'LECTURER', 'C': 'TALKING', 'D': 'TALKING'}, {'C': 'STILL'}],
    # Speech at A remains attributed to the lecturer, even during group work.
    'discussion': [{'A': 'LECTURER', 'C': 'STILL'}, {'A': 'LECTURER', 'C': 'TALKING'},
                   {'A': 'LECTURER', 'C': 'STILL'}],
    # Loud levels are set for B-D in every run: only the rowdy phase is LOUD.
    'demo': [{'C': 'STILL'}, {'A': 'LECTURER', 'B': 'STILL', 'C': 'STILL'},
             {'B': 'STILL', 'C': 'TALKING', 'D': 'TALKING'},
             {'A': 'LECTURER', 'B': 'STILL', 'C': 'LOUD', 'D': 'LOUD'},
             {'C': 'STILL', 'D': 'STILL'}, {}, {}, {}, {}],
}


def play(scenario: scenarios.Scenario, mode: p.Mode, seed: int, *, aligned=False,
         calibrate: bool | None = None) -> list[tuple[str, str, str]]:
    """Phase-end states with independent clocks and exact PC delivery times.
    calibrate defaults to True only for the reference scenario."""
    sim = Simulator(nodes=4, seed=seed, scenario=scenario, aligned=aligned,
                    receive_jitter_s=0 if aligned else 0.08)
    config = FusionConfig()
    # As if each student node's loud level had been captured: no other phase
    # may reach it (talking, lecture bleed), so every scenario checks that too.
    config.loud_levels_x16 = scenarios.sim_loud_levels(config.zones, config.reference_zone)
    engine = FusionEngine(config)
    if calibrate is None:
        calibrate = scenario is scenarios.SCENARIOS["reference"]
    if calibrate:
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
            name = next(name for name, value in scenarios.SCENARIOS.items() if value is scenario)
            actual = {z['zone']: z['state'] for z in s['zones']}
            wanted_loud = {zone for zone, state in EXPECTED_ZONES.get(name, {}) and
                           EXPECTED_ZONES[name][boundaries[step]].items() if state == 'LOUD'}
            assert {zone for zone, state in actual.items() if state == 'LOUD'} == wanted_loud, (
                name, boundaries[step], actual)
            if name in EXPECTED_ZONES:
                actual = {z['zone']: z['state'] for z in s['zones']}
                for zone, expected in EXPECTED_ZONES[name][boundaries[step]].items():
                    assert actual[zone] == expected, (name, boundaries[step], zone, actual)
            if scenario is scenarios.SCENARIOS["reference"] and calibrate:
                students = s["reference"]["zones"]
                assert all(z["gain_q16"] is not None for z in students.values())
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

    def test_every_phase_without_voice_setup(self):
        # Every node hears the lecturer as SPEECH; without calibration the
        # loudness fallback must still tell lecture from student talk.
        for (name, mode), expected in EXPECTED.items():
            with self.subTest(scenario=name, mode=mode.name):
                self.assertEqual(play(scenarios.SCENARIOS[name], mode, 3, calibrate=False), expected)

    def test_every_phase_with_voice_setup(self):
        for (name, mode), expected in EXPECTED.items():
            with self.subTest(scenario=name, mode=mode.name):
                self.assertEqual(play(scenarios.SCENARIOS[name], mode, 3, calibrate=True), expected)

    def test_last_phase_holds(self):
        scenario = scenarios.SCENARIOS["exam"]
        index, phase = scenario.phase_at(scenario.seconds + 1000)
        self.assertEqual((index, phase), (len(scenario.phases) - 1, scenario.phases[-1]))

    def test_clock_pause_speed_and_skip(self):
        clock = scenarios.ScriptClock(scenarios.SCENARIOS["lecture"])  # 40 s, 120 s, 200 s, 90 s
        clock.start(100.0)
        self.assertEqual(clock.elapsed(110.0), 10.0)
        clock.set_paused(110.0, True)
        self.assertEqual(clock.elapsed(500.0), 10.0)       # Paused: the script holds
        self.assertEqual(clock.drift_rate, 1)
        clock.set_paused(500.0, False)
        clock.set_rate(500.0, 4)
        self.assertEqual(clock.elapsed(500.0), 10.0)       # Changing speed doesn't jump
        self.assertEqual(clock.elapsed(505.0), 30.0)
        self.assertEqual(clock.drift_rate, 4)
        with self.assertRaises(ValueError):
            clock.set_rate(505.0, 3)
        self.assertTrue(clock.next_phase(505.0))           # To the start of phase 2
        self.assertEqual((clock.elapsed(505.0), clock.phase(505.0)[0], clock.jumps), (40.0, 1, 1))
        self.assertTrue(clock.next_phase(505.0))
        self.assertTrue(clock.next_phase(505.0))
        self.assertFalse(clock.next_phase(505.0))          # Already on the last phase
        self.assertEqual((clock.phase(505.0)[0], clock.jumps), (3, 3))

    def test_skip_moves_the_room_and_speed_keeps_pace(self):
        demo = scenarios.SCENARIOS["demo"]
        target = demo.phases.index(scenarios.CO2_BUILDS)
        clock = scenarios.ScriptClock(demo)
        sim = Simulator(4, seed=1, scenario=demo, clock=clock, warmup_s=0)
        sim.poll(0.0)
        for _ in range(target):
            clock.next_phase(0.5)
        sim.poll(2.0)
        zone = scenarios.CO2_BUILDS.zone(1)
        for node in sim.nodes:  # Air is already where the new phase puts it, give or take noise
            self.assertAlmostEqual(node.co2_ppm, scenarios.CO2_BUILDS.zone(node.node_id).co2_ppm, delta=20)
        self.assertAlmostEqual(sim.nodes[0].temperature_c, zone.temperature_c, delta=0.3)

        def co2_after(rate):  # 20 s of reports after a jump to the window-open phase
            c = scenarios.ScriptClock(demo)
            s = Simulator(1, seed=2, scenario=demo, clock=c, warmup_s=0)
            s.poll(0.0)
            for _ in range(target):
                c.next_phase(0.1)
            s.poll(0.5)
            c.next_phase(1.0)
            s.nodes[0].co2_ppm = scenarios.CO2_BUILDS.zone(1).co2_ppm  # Start from the closed room
            s.nodes[0].seen_jumps = c.jumps
            c.set_rate(1.0, rate)
            s.poll(21.0)
            return s.nodes[0].co2_ppm
        start, goal = scenarios.CO2_BUILDS.zone(1).co2_ppm, scenarios.WINDOW_OPEN.zone(1).co2_ppm
        self.assertLess(abs(co2_after(4) - goal), abs(co2_after(1) - goal) / 3)  # 4x catches up faster
        self.assertGreater(start, goal)

    def test_aligned_reference_fixture_still_available(self):
        self.assertEqual(play(scenarios.SCENARIOS["reference"], p.Mode.LECTURE, 1, aligned=True),
                         EXPECTED["reference", p.Mode.LECTURE])


if __name__ == "__main__":
    unittest.main()
