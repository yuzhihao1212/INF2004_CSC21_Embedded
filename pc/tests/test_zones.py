"""Zone decisions, exact integer boundaries and layout contract."""
import json
import tempfile
import unittest
from pathlib import Path
from mosaic import protocol as p
from mosaic.fusion import FusionConfig, FusionEngine, ZoneView
from mosaic.reference import ReferenceFusion, round_ratio, seconds_to_ms
from tests.test_fusion import telemetry, QUIET, SPEECH, CHAT
from tests.test_reference import window


class ZoneStates(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine(FusionConfig(zone_dwell_ms=0, audio_smooth_ms=0, motion_window_ms=0))
        self.seq = 0

    def feed(self, node=3, now=0, **kwargs):
        self.seq += 2
        self.engine.add(node, telemetry(**kwargs), now)
        self.engine.evaluate(now, {node})
        return next(z for z in self.engine.state()['zones'] if z['node_id'] == node)

    def test_every_activity_rule(self):
        for node, probs, pir, state in ((3, QUIET, 0, 'STILL'), (3, QUIET, 10, 'MOTION'),
                                       (1, SPEECH, 0, 'LECTURER'), (3, CHAT, 0, 'TALKING')):
            with self.subTest(state=state):
                self.assertEqual(self.feed(node, self.seq, probs=probs, pir=pir)['state'], state)

    def test_lecturer_must_be_dominant_and_in_reference_zone(self):
        self.assertEqual(self.feed(1, probs=(55, 43, 0, 2))['state'], 'STILL')
        self.assertEqual(self.feed(2, now=1, probs=SPEECH)['state'], 'TALKING')

    def test_dwell_and_interrupted_candidate(self):
        self.engine.config.zone_dwell_ms = 10000
        self.assertEqual(self.feed(now=0)['state'], 'NO_DATA')
        self.assertEqual(self.feed(now=9.999)['state'], 'NO_DATA')
        self.assertEqual(self.feed(now=10)['state'], 'STILL')
        self.assertEqual(self.feed(now=11, pir=30)['state'], 'STILL')
        self.feed(now=19)  # Interrupted: next motion needs a new full dwell.
        self.assertEqual(self.feed(now=20, pir=30)['state'], 'STILL')
        self.assertEqual(self.feed(now=29.999, pir=30)['state'], 'STILL')
        self.assertEqual(self.feed(now=30, pir=30)['state'], 'MOTION')
        self.engine.evaluate(30, set())
        self.assertEqual(self.engine.state()['zones'][2]['state'], 'NO_DATA')

    def test_no_audio_offline_and_stale(self):
        self.feed(probs=CHAT)
        self.engine.evaluate(0, set(), {3})
        c = self.engine.state()['zones'][2]
        self.assertEqual((c['state'], c['status']), ('TALKING', 'STALE'))
        self.engine.add(3, p.Telemetry(), 1)
        self.engine.evaluate(1, {3})
        self.assertEqual(self.engine.state()['zones'][2]['state'], 'NO_DATA')
        self.engine.evaluate(2, set())
        for zone in self.engine.state()['zones']:
            self.assertEqual((zone['state'], zone['air'], zone['comfort'], zone['status']),
                             ('NO_DATA', 'UNKNOWN', 'UNKNOWN', 'OFFLINE'))
            self.assertIsNone(zone['co2_ppm'])
        self.assertEqual(len(self.engine.state()['zones']), 4)

    def test_air_boundaries_and_invalid_reading(self):
        for ppm, air in ((799, 'GOOD'), (800, 'FAIR'), (1199, 'FAIR'), (1200, 'POOR')):
            with self.subTest(ppm=ppm):
                self.assertEqual(self.feed(now=ppm, co2=ppm)['air'], air)
        self.assertEqual(self.feed(now=1201, co2_valid=False)['air'], 'UNKNOWN')

    def test_comfort_boundaries_and_hysteresis(self):
        self.assertEqual(self.feed(temp=28, humidity=70)['comfort'], 'COMFORTABLE')
        self.assertEqual(self.feed(now=1, temp=28.1)['comfort'], 'OUT_OF_RANGE')
        self.assertEqual(self.feed(now=2, temp=27.8)['comfort'], 'OUT_OF_RANGE')
        self.assertEqual(self.feed(now=3, temp=27.5)['comfort'], 'COMFORTABLE')
        self.assertEqual(self.feed(now=4, humidity=70.1)['comfort'], 'OUT_OF_RANGE')
        self.assertEqual(self.feed(now=5, humidity=67)['comfort'], 'COMFORTABLE')

    def test_calibrated_reference_overrides_misleading_class_probabilities(self):
        self.engine = FusionEngine(FusionConfig(zone_dwell_ms=0))
        self.engine.calibrate(0)
        seq = 0
        def pair(now, ref, local):
            nonlocal seq
            seq += 1
            for node, level in ((1, ref), (3, local)):
                self.engine.add(node, p.Telemetry(audio_window_seq=seq,
                    audio=(window(level, CHAT),)), now)
            self.engine.evaluate(now, {1, 3})
        for i in range(20):
            pair(i / 2, 40 + 2 * i, 20 + i)
        for i in range(1, 22):
            pair(9.5 + i / 2, 60, 30)
        self.assertEqual(self.engine.state()['zones'][2]['state'], 'STILL')
        for i in range(1, 24):
            pair(20 + i / 2, 60, 100)
        self.assertEqual(self.engine.state()['zones'][2]['state'], 'TALKING')


class Layout(unittest.TestCase):
    def test_default_and_explicit_custom_map(self):
        self.assertEqual(FusionConfig().zone_layout,
                         {'A': [0, 0], 'B': [1, 0], 'C': [2, 0], 'D': [3, 0]})
        cfg = FusionConfig(zones={1: 'Desk', 3: 'Rear'}, zone_layout={'Desk': [0, 1], 'Rear': [2, 0]})
        self.assertEqual(FusionEngine(cfg).state()['zone_layout'], cfg.zone_layout)

    def test_invalid_layouts(self):
        default = FusionConfig().zone_layout
        for layout in ({}, default | {'E': [3, 3]}, default | {'C': [0, 0]},
                       default | {'C': [-1, 0]}, default | {'C': [0.5, 0]},
                       default | {'C': [True, 0]}, default | {'C': [8, 0]},
                       default | {'C': [0]}, []):
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                FusionConfig(zone_layout=layout)
        with self.assertRaises(ValueError):
            FusionConfig(zones={1: 'A', 3: 'A'})

    def test_unit_suffixed_json_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fusion.json'
            path.write_text(json.dumps({'zone_dwell_ms': 7000, 'temp_max_x10': 290,
                'reference_talking_pct': 60, 'zone_layout': FusionConfig().zone_layout}))
            cfg = FusionConfig.from_json(path)
            self.assertEqual((cfg.zone_dwell_ms, cfg.temp_max_x10, cfg.reference_talking_pct), (7000, 290, 60))
            for old in ('activity_dwell_s', 'reference_talking_fraction', 'temp_max_c'):
                path.write_text(json.dumps({old: 10}))
                with self.assertRaises(ValueError):
                    FusionConfig.from_json(path)


class IntegerBoundaries(unittest.TestCase):
    def test_rounding_half_away_and_clock(self):
        for numerator, denominator, answer in ((1, 2, 1), (-1, 2, -1), (3, 2, 2),
                                               (-3, 2, -2), (1, 3, 0)):
            self.assertEqual(round_ratio(numerator, denominator), answer)
        self.assertEqual(seconds_to_ms(1.0005), 1001)
        self.assertEqual(seconds_to_ms(-1.0005), -1001)
        for value in (float('nan'), float('inf'), True, '1'):
            with self.assertRaises(ValueError):
                seconds_to_ms(value)

    def test_sums_compare_without_rounding_the_mean(self):
        # 39.5 rounds to 40 for display, but must NOT meet a 40% decision gate.
        view = ZoneView('C', 3, (0, 79, 0, 0), 2, 19, 2, None, None, None, False)
        self.assertFalse(view.prob_at_least(p.AudioClass.SPEECH, 40))
        self.assertFalse(view.motion(10))
        self.assertTrue(view.prob_at_least(p.AudioClass.SPEECH, 39))

    def test_wire_bounds_clamp_environment_and_reject_decimal_config(self):
        engine = FusionEngine()
        engine.add(1, p.Telemetry(temperature_x10=-99999, humidity_x10=99999,
            co2_ppm=99999, pir_active_pct=200, valid_flags=p.Valid.TEMP_HUM | p.Valid.CO2 | p.Valid.PIR), 0)
        engine.evaluate(0, {1})
        zone = engine.state()['zones'][0]
        self.assertEqual((zone['temperature_x10'], zone['humidity_x10'], zone['co2_ppm'], zone['motion_pct']),
                         (-32768, 1000, 65535, 100))
        for kwargs in ({'activity_dwell_ms': 1.5}, {'temp_max_x10': 28.0},
                       {'zone_dwell_ms': -1}, {'widespread_pct': 101}):
            with self.assertRaises(ValueError):
                FusionConfig(**kwargs)

    def test_q16_power_extremes_and_strict_threshold(self):
        from mosaic.reference import _Student, _Window
        ref = ReferenceFusion({1: 'A', 3: 'C'})
        model = _Student(gain_q16=65536, background_power_x256=0, upper_residual_x256=0)
        self.assertFalse(ref._levels(model, _Window(0, 65535, 90), _Window(0, 65535, 90)))
        self.assertEqual(model.expected_power_x256, 65535 ** 2)
        self.assertFalse(ref._levels(model, _Window(0, 320, 90), _Window(0, 464, 90)))
        self.assertTrue(ref._levels(model, _Window(0, 320, 90), _Window(0, 465, 90)))
        self.assertFalse(ref._levels(model, _Window(0, 0, 90), _Window(0, 64, 90)))

    def test_runtime_state_and_histories_contain_no_floats(self):
        engine = FusionEngine()
        engine.calibrate(0)
        for i in range(30):
            for node in range(1, 5):
                engine.add(node, p.Telemetry(audio_window_seq=i + 1,
                    audio=(window(40 + i if node == 1 else 20 + i // 2),)), i / 2)
            engine.evaluate(i / 2, {1, 2, 3, 4})
        def check(value, seen):
            self.assertNotIsInstance(value, float)
            if id(value) in seen:
                return
            seen.add(id(value))
            if isinstance(value, dict):
                for child in value.values(): check(child, seen)
            elif isinstance(value, (list, tuple)) or type(value).__name__ == 'deque':
                for child in value: check(child, seen)
            elif type(value).__module__ in {'mosaic.fusion', 'mosaic.reference'} and hasattr(value, '__dict__'):
                check(vars(value), seen)
        check(engine, set())
        check(engine.state(), set())
