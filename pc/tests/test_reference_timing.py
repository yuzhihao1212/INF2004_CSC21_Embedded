"""Independent Pico clocks and report batching, replayed without sleeping.

Metrics are time shares sampled every 50 ms, not repeated samples masquerading
as independent audio windows. 'talking_share' uses the rolling decision when
available, and 'raw_talking_share' always measures the unchanged window policy.
Lecture-only shares include the normal release tail after students stop. New
noise entries are forbidden during lecture; an existing alert may take the
documented smoothing + activity dwell time to clear at that transition.
"""

import json
import math
import unittest
from dataclasses import replace

from mosaic import protocol as p, scenarios
from mosaic.fusion import FusionEngine
from mosaic.simulator import Simulator

REPORTED_PHASES = {1: (0.00, 0.40), 2: (0.10, 0.20),
                   3: (0.35, 0.65), 4: (0.25, 0.50)}
CASES = [("reported", 1, REPORTED_PHASES),
         ("near_boundary", 4, {1: (0.0, 0.49), 3: (0.49, 0.02)})]
CASES += [(f"seed_{seed}", seed, None) for seed in (2, 7, 19, 42)]


def replay(seed=1, phases=None, *, aligned=False):
    scenario = scenarios.SCENARIOS["reference"]
    scenario = replace(scenario, phases=tuple(
        replace(phase, seconds=150) if i == 2 else phase
        for i, phase in enumerate(scenario.phases)))
    sim = Simulator(4, seed=seed, scenario=scenario, aligned=aligned,
                    receive_jitter_s=0 if aligned else 0.08, phases=phases)
    engine = FusionEngine()
    engine.calibrate(0)
    started = sum(phase.seconds for phase in scenario.phases[:2])
    ended = started + scenario.phases[2].seconds
    latest = {}
    raw = talking = lecture = lecture_talking = 0
    events = []
    step_s = 0.05
    for step in range(round(scenario.seconds / step_s)):
        now = step * step_s
        for received, data in sim.poll(now):
            header, telemetry = p.decode(data)
            latest[header.node_id] = received
            engine.add(header.node_id, telemetry, received,
                       reboot=bool(header.flags & p.FLAG_FIRST_SINCE_BOOT))
            engine.evaluate(received, {n for n, t in latest.items() if received - t <= 3})
            events.extend(engine.drain_events())
        engine.evaluate(now, {n for n, t in latest.items() if now - t <= 3})
        events.extend(engine.drain_events())
        status = engine.state()["reference"]["zones"]["C"]
        effective = status.get("smoothed_state", status["state"])
        if started <= now < ended:
            raw += status["state"] == "TALKING"
            talking += effective == "TALKING"
        else:
            lecture += 1
            lecture_talking += effective == "TALKING"
    noise = [e.time - started for e in events if e.new == "NOISE_RISING" and e.time >= started]
    false_entries = [e.time for e in events if e.new == "NOISE_RISING"
                     and not started <= e.time < ended]
    return {"raw_talking_share": round(raw * step_s / (ended - started), 4),
            "talking_share": round(talking * step_s / (ended - started), 4),
            "lecture_talking_share": round(lecture_talking / lecture, 4),
            "noise_after_s": round(noise[0], 3) if noise else None,
            "lecture_noise_entries": false_entries,
            "sustained": any(e.new == "SUSTAINED_CHATTER" for e in events)}


class RealisticReference(unittest.TestCase):
    def test_independent_clocks_do_not_reset_classroom_dwell(self):
        results = [(name, replay(seed, phases)) for name, seed, phases in CASES]
        for name, result in results:
            print(f"TIMING {name}: {json.dumps(result, sort_keys=True)}")
            with self.subTest(case=name):
                self.assertIsNotNone(result["noise_after_s"], f"NOISE_RISING never reached: {result}")
                self.assertLessEqual(result["noise_after_s"], 45, result)
                self.assertGreaterEqual(result["talking_share"], 0.8, result)
                self.assertLessEqual(result["lecture_talking_share"], 0.05, result)
                self.assertEqual(result["lecture_noise_entries"], [], result)

    def test_aligned_control(self):
        result = replay(aligned=True)
        self.assertLessEqual(result["noise_after_s"], 45)
        self.assertGreaterEqual(result["talking_share"], 0.9)
        self.assertTrue(result["sustained"])


class SimulatorTiming(unittest.TestCase):
    def test_seeded_independent_phases_and_receive_jitter(self):
        first = Simulator(4, seed=3, receive_jitter_s=0.08)
        second = Simulator(4, seed=3, receive_jitter_s=0.08)
        self.assertEqual(first.nodes, second.nodes)
        self.assertEqual(len({n.audio_phase_s for n in first.nodes}), 4)
        self.assertEqual(len({n.report_phase_s for n in first.nodes}), 4)
        first.poll(0)
        second.poll(0)
        self.assertEqual(first.poll(5), second.poll(5))
        self.assertTrue(any(n.last_audio_index >= 8 for n in first.nodes))

    def test_phase_slips_and_two_window_wire_cap(self):
        sim = Simulator(1, seed=1, phases={1: (0, 0.4)})
        sim.nodes[0].audio_period_s = 0.49
        sim.poll(0)
        packets = sim.poll(30)
        decoded = [p.decode(data)[1] for _, data in packets]
        self.assertEqual(len(decoded[0].audio), 1)
        self.assertTrue(all(len(t.audio) <= 2 for t in decoded))
        self.assertTrue(any((b.audio_window_seq - a.audio_window_seq) % 65536 > len(b.audio)
                            for a, b in zip(decoded, decoded[1:])))

    def test_rms_uses_true_audio_time_not_report_or_receive_time(self):
        sim = Simulator(1, seed=1, scenario=scenarios.SCENARIOS["reference"],
                        phases={1: (0.0, 0.4)}, receive_jitter_s=0.08)
        sim.poll(0)
        received, data = sim.poll(0.5)[0]
        _, telemetry = p.decode(data)
        self.assertTrue(0.4 <= received <= 0.48)
        self.assertEqual(telemetry.audio[0].rms, 100)  # True completion = 0.0.
        _, data = sim.poll(1.5)[0]
        _, telemetry = p.decode(data)
        self.assertEqual([w.rms_x16 for w in telemetry.audio],
                         [round(100 * (1 + 0.25 * math.sin(t * 0.8)) * 16) for t in (0.5, 1.0)])

    def test_coarse_and_fine_polling_have_identical_deliveries(self):
        coarse = Simulator(3, seed=7, receive_jitter_s=0.08)
        fine = Simulator(3, seed=7, receive_jitter_s=0.08)
        coarse.poll(0)
        fine.poll(0)
        fine_packets = []
        for i in range(1, 101):
            fine_packets.extend(fine.poll(i / 10))
        self.assertEqual(coarse.poll(10), fine_packets)


if __name__ == "__main__":
    unittest.main()
