"""Compare the frozen pre-integer algorithm against every realistic scenario.

Contract: identical classroom states in order, every transition within 1000 ms.
The simulator's float waveform/timing generator is test input, not fusion math.
"""
import hashlib
import unittest
from mosaic import protocol as p, scenarios
from mosaic.fusion import FusionEngine
from mosaic.simulator import Simulator
from tests.float_reference.fusion import FusionEngine as FloatFusion
from pathlib import Path

SEEDS = (1, 2, 7)
REGIONS = ('activity', 'air', 'comfort')
ORACLE_HASHES = {
    'fusion': 'c7fd75244f9b402ce2cc5c34a3d4f55801e305aec3d4bf7399f20ff1e45be095',
    'reference': '39d3595e54c2652a33fceefbaf6ca90eea5636ad53ec2488e1a3f1848aa5a260',
}


def compare_scenario(name, seed, mode=p.Mode.LECTURE):
    scenario = scenarios.SCENARIOS[name]
    sim = Simulator(4, seed=seed, scenario=scenario, receive_jitter_s=0.08)
    integer, floating = FusionEngine(), FloatFusion()
    engines = (integer, floating)
    for engine in engines:
        engine.set_mode(mode, 0)
        if name == 'reference':
            engine.calibrate(0)
    events = [[], []]
    latest = {}
    for step in range(round(scenario.seconds * 10)):
        now = step / 10
        for received, data in sim.poll(now):
            header, telemetry = p.decode(data)
            latest[header.node_id] = received
            online = {n for n, t in latest.items() if received - t <= 3}
            for i, engine in enumerate(engines):
                engine.add(header.node_id, telemetry, received,
                           reboot=bool(header.flags & p.FLAG_FIRST_SINCE_BOOT))
                engine.evaluate(received, online)
                events[i].extend(engine.drain_events())
        online = {n for n, t in latest.items() if now - t <= 3}
        for i, engine in enumerate(engines):
            engine.evaluate(now, online)
            events[i].extend(engine.drain_events())
    results = {}
    for region in REGIONS:
        actual = [(e.new, e.time_ms) for e in events[0] if e.region == region]
        expected = [(e.new, e.time * 1000) for e in events[1] if e.region == region]
        same = [s for s, _ in actual] == [s for s, _ in expected]
        delta = max((abs(a[1] - b[1]) for a, b in zip(actual, expected)), default=0)
        results[region] = (same, delta, len(expected), actual, expected)
    return results


class IntegerAccuracy(unittest.TestCase):
    def test_float_oracle_is_frozen(self):
        for name, digest in ORACLE_HASHES.items():
            source = (Path(__file__).with_name('float_reference') / (name + '.py')).read_text()
            source = source.replace('from .reference import', 'from mosaic.reference import')
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), digest)

    def test_every_scenario_sequence_and_transition_time(self):
        maximum = {region: 0 for region in REGIONS}
        counts = {region: 0 for region in REGIONS}
        for name in scenarios.SCENARIOS:
            modes = (p.Mode.LECTURE, p.Mode.DISCUSSION) if name == 'discussion' else (p.Mode.LECTURE,)
            for mode in modes:
                for seed in SEEDS:
                    results = compare_scenario(name, seed, mode)
                    for region, (same, delta, count, actual, expected) in results.items():
                        with self.subTest(scenario=name, seed=seed, mode=mode.name, region=region):
                            self.assertTrue(same, (actual, expected))
                            self.assertLessEqual(delta, 1000, (actual, expected))
                        maximum[region] = max(maximum[region], delta)
                        counts[region] += count
        for region in REGIONS:
            print(f'FLOAT VS INTEGER {region}: same sequence; transitions={counts[region]}; max_delta_ms={maximum[region]:.3f}')
