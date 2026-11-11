"""Compare integer fusion with the float baseline under the same speech policy.

Contract: identical classroom states in order, every transition within 1000 ms.
The simulator's float waveform/timing generator is test input, not fusion math.
"""
import hashlib
import unittest
from mosaic import protocol as p, scenarios
from mosaic.fusion import FusionConfig, FusionEngine
from mosaic.simulator import Simulator
from tests.float_reference import fusion as frozen
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SEEDS = (1, 2, 7)
UNCALIBRATED_LOCAL_RMS_PCT = FusionConfig().uncalibrated_local_rms_pct
REGIONS = ('activity', 'air', 'comfort')
ORACLE_HASHES = {
    'fusion': 'c7fd75244f9b402ce2cc5c34a3d4f55801e305aec3d4bf7399f20ff1e45be095',
    'reference': '39d3595e54c2652a33fceefbaf6ca90eea5636ad53ec2488e1a3f1848aa5a260',
}


class _LegacyProtocol:
    # The frozen occupancy check adds slots 2 and 3. Slot 3 is now zero,
    # so the same float arithmetic tests the new SPEECH evidence.
    AudioClass = SimpleNamespace(LECTURER_SPEECH=p.AudioClass.SPEECH,
                                 STUDENT_CONVERSATION=p.AudioClass.RESERVED)

    def __getattr__(self, name):
        return getattr(p, name)


class FloatFusion(frozen.FusionEngine):
    """Apply the new location rules to the frozen float means and dwell."""

    def add(self, node_id, t, now, **kwargs):
        # The frozen engine keeps no audio levels; record them alongside.
        if node_id in self.config.zones:
            levels = self.__dict__.setdefault('_levels', {}).setdefault(node_id, deque())
            levels.extend((now, w.rms_x16) for w in t.audio)
        super().add(node_id, t, now, **kwargs)

    def _mean_level(self, node_id):
        levels = self.__dict__.get('_levels', {}).get(node_id, deque())
        while levels and levels[0][0] < self._now - self.config.audio_smooth_s:
            levels.popleft()
        return sum(v for _, v in levels) / len(levels) if levels else 0.0

    def _lecturer_view(self, views):
        for view in views:
            if view.zone == self.config.reference_zone:
                speech = view.prob(p.AudioClass.SPEECH)
                if speech >= self.config.lecture_speech_pct and speech == max(view.probs):
                    return view
        return None

    def _occupied_candidate(self, state, now):
        cfg = self.config
        noisy = state in frozen._NOISY
        if self.mode == p.Mode.QUIET_WORK:
            threshold = (cfg.quiet_work_conversation_exit_pct if noisy
                         else cfg.quiet_work_conversation_enter_pct)
        else:
            threshold = cfg.conversation_exit_pct if noisy else cfg.conversation_enter_pct
        views = [v for v in self._views if v.probs]
        students = [v for v in views if v.zone != cfg.reference_zone]
        lecturer = self._lecturer_view(views)
        talking = []
        for view in students:
            result = self._reference_summary(view.node_id)["smoothed_state"]
            bleed = (lecturer is not None and self._mean_level(view.node_id) * 100
                     < UNCALIBRATED_LOCAL_RMS_PCT * self._mean_level(lecturer.node_id))
            if result == "TALKING" or (result == "UNKNOWN" and not bleed
                                       and view.prob(p.AudioClass.SPEECH) >= threshold):
                talking.append(view.zone)

        activity = frozen.Activity
        if self.mode == p.Mode.DISCUSSION:
            if talking and len(talking) / len(students) >= cfg.widespread_fraction:
                return activity.DISCUSSION, "student speech"
        elif talking:
            if (state == activity.SUSTAINED_CHATTER or
                    state == activity.NOISE_RISING and now - self.activity.since >= cfg.chatter_after_s):
                return activity.SUSTAINED_CHATTER, "student speech"
            return activity.NOISE_RISING, "student speech"

        if not talking and lecturer is not None:
            return activity.FOCUSED_LECTURE, "lecturer speech"
        return activity.QUIET, "no dominant activity"


@patch.object(frozen, 'p', _LegacyProtocol())
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
