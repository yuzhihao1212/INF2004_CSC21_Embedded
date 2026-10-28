"""Scripted classroom scenarios for pc/mosaic/fusion.py (design assumption A5).

Run from the pc/ folder:  python -m unittest -v

Each scenario feeds four zones one TELEMETRY per second and evaluates once a
second, as the gateway does. Probabilities are (background, lecturer speech,
student conversation, transient noise) in %.
"""

import json
import tempfile
import unittest
from pathlib import Path

from mosaic import protocol as p
from mosaic.fusion import Activity, Air, Comfort, FusionConfig, FusionEngine

QUIET = (90, 5, 3, 2)
SPEECH = (10, 75, 10, 5)
CHAT = (10, 15, 70, 5)
MURMUR = (40, 25, 30, 5)    # Conversation between the exit (25) and enter (40) thresholds
BANG = (5, 5, 5, 85)
ALL = (1, 2, 3, 4)


def telemetry(probs=QUIET, pir=0, co2=600, temp=24.0, humidity=55.0, co2_valid=True):
    valid = p.Valid.PIR | p.Valid.TEMP_HUM | (p.Valid.CO2 if co2_valid else p.Valid.CO2_WARMUP)
    window = p.AudioWindow(160, p.AudioClass.UNKNOWN, probs)
    return p.Telemetry(temperature_x10=round(temp * 10), humidity_x10=round(humidity * 10),
                       co2_ppm=co2, audio=(window, window), pir_active_pct=pir,
                       valid_flags=valid)


class Scenario(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine()
        self.now = 0.0
        self.online = set(ALL)

    def run_for(self, seconds, **zones):
        """zones: node_id -> telemetry kwargs, e.g. run_for(30, n1=dict(probs=SPEECH)).
        Nodes not named get default (quiet, empty room) readings."""
        for _ in range(int(seconds)):
            self.now += 1.0
            for node_id in self.online:
                self.engine.add(node_id, telemetry(**zones.get(f"n{node_id}", {})), self.now)
            self.engine.evaluate(self.now, self.online)
        return self.engine.state()

    def every(self, **kwargs):
        return {f"n{n}": kwargs for n in ALL}

    def assert_states(self, activity=None, air=None, comfort=None):
        if activity:
            self.assertEqual(self.engine.activity.state, activity)
        if air:
            self.assertEqual(self.engine.air.state, air)
        if comfort:
            self.assertEqual(self.engine.comfort.state, comfort)

    def change_time(self, region, new):
        return next(e.time_ms / 1000 for e in self.engine.events if e.region == region and e.new == new)


class Occupancy(Scenario):
    def test_starts_unknown_then_empty(self):
        self.assert_states(Activity.UNKNOWN)
        self.run_for(19)
        self.assert_states(Activity.UNKNOWN)
        self.run_for(2)
        self.assert_states(Activity.EMPTY, Air.NORMAL, Comfort.COMFORTABLE)

    def test_motion_makes_occupied(self):
        self.run_for(30)
        self.run_for(40, n3=dict(pir=40))  # 60 s motion average crosses 10 %, then the dwell
        self.assert_states(Activity.QUIET)
        self.assertTrue(self.engine.state()["occupied"])

    def test_still_class_stays_occupied(self):
        """PIR is motion, not presence: no motion at all, but a lecture."""
        self.run_for(30)
        self.run_for(60, n1=dict(probs=SPEECH))
        self.assert_states(Activity.FOCUSED_LECTURE)
        # Silent exam with raised CO2 and nobody moving: still occupied.
        self.run_for(900, **self.every(co2=900))
        self.assert_states(Activity.QUIET)

    def test_empty_needs_long_quiet(self):
        self.run_for(30)
        self.run_for(60, n1=dict(probs=SPEECH, pir=30))
        # Quiet, still, fresh air. Motion stays in the 60 s average for ~40 s,
        # then EMPTY needs 600 s without any evidence.
        self.run_for(620)
        self.assertTrue(self.engine.activity.state.occupied)
        self.run_for(30)
        self.assert_states(Activity.EMPTY)

    def test_offline_zones(self):
        self.run_for(30)
        self.assertEqual(self.engine.state()["confidence_pct"], 100)
        self.engine.evaluate(self.now, online={1, 2}, stale={3})
        self.assertEqual(self.engine.state()["confidence_pct"], 63)  # (2 + 0.5) / 4
        self.engine.evaluate(self.now, online=set())
        self.assert_states(Activity.UNKNOWN, Air.UNKNOWN, Comfort.UNKNOWN)


class Lecture(Scenario):
    def setUp(self):
        super().setUp()
        self.run_for(30)
        self.lecture = dict(n1=dict(probs=SPEECH, pir=20), n2=dict(probs=SPEECH))
        self.run_for(60, **self.lecture)
        self.assert_states(Activity.FOCUSED_LECTURE)

    def test_transient_noise_ignored(self):
        """One loud bang (a dropped book) in every zone changes nothing."""
        self.run_for(1, **self.every(probs=BANG))
        self.run_for(30, **self.lecture)
        self.assert_states(Activity.FOCUSED_LECTURE)
        self.assertEqual(sum(e.region == "activity" for e in self.engine.events), 3)

    def test_rear_chatter_rises_then_sustains_then_settles(self):
        chatter = dict(self.lecture, n3=dict(probs=CHAT), n4=dict(probs=CHAT))
        start = self.now
        self.run_for(40, **chatter)
        self.assert_states(Activity.NOISE_RISING)
        rising = self.change_time("activity", "NOISE_RISING")
        self.assertLessEqual(rising - start, 10 + 20 + 1)  # Smoothing fills, then the dwell

        self.run_for(130, **chatter)
        self.assert_states(Activity.SUSTAINED_CHATTER)
        self.assertAlmostEqual(self.change_time("activity", "SUSTAINED_CHATTER") - rising, 120, delta=1)

        # Murmur sits between the thresholds: the exit bar holds it in the state.
        self.run_for(60, **dict(self.lecture, n3=dict(probs=MURMUR), n4=dict(probs=MURMUR)))
        self.assert_states(Activity.SUSTAINED_CHATTER)
        self.run_for(60, **self.lecture)
        self.assert_states(Activity.FOCUSED_LECTURE)

    def test_murmur_alone_does_not_start_noise_rising(self):
        self.run_for(120, **dict(self.lecture, n3=dict(probs=MURMUR), n4=dict(probs=MURMUR)))
        self.assert_states(Activity.FOCUSED_LECTURE)

    def test_quiet_work_mode_is_stricter(self):
        self.engine.set_mode(p.Mode.QUIET_WORK, self.now)
        self.run_for(60, **dict(self.lecture, n3=dict(probs=MURMUR), n4=dict(probs=MURMUR)))
        self.assert_states(Activity.NOISE_RISING)


class Discussion(Scenario):
    def setUp(self):
        super().setUp()
        self.run_for(30)
        self.run_for(60, n1=dict(probs=SPEECH, pir=20))

    def test_discussion_mode(self):
        self.engine.set_mode(p.Mode.DISCUSSION, self.now)
        self.run_for(40, **self.every(probs=CHAT, pir=30))
        self.assert_states(Activity.DISCUSSION)
        self.run_for(200, **self.every(probs=CHAT, pir=30))
        self.assert_states(Activity.DISCUSSION)  # Never becomes chatter in this mode
        # Exit: the discussion ends and the lecturer resumes.
        self.run_for(60, n1=dict(probs=SPEECH, pir=20))
        self.assert_states(Activity.FOCUSED_LECTURE)
        self.assertEqual(self.engine.events[-1].old, "DISCUSSION")

    def test_same_room_in_lecture_mode_is_noise(self):
        self.run_for(40, **self.every(probs=CHAT, pir=30))
        self.assert_states(Activity.NOISE_RISING)

    def test_one_group_talking_is_not_discussion(self):
        self.engine.set_mode(p.Mode.DISCUSSION, self.now)
        self.run_for(60, n1=dict(probs=SPEECH, pir=20), n4=dict(probs=CHAT))
        self.assert_states(Activity.FOCUSED_LECTURE)


class Environment(Scenario):
    def test_poor_ventilation_and_recovery(self):
        self.run_for(30)
        self.assert_states(air=Air.NORMAL)
        self.run_for(59, n2=dict(co2=1250))
        self.assert_states(air=Air.NORMAL)
        self.run_for(2, n2=dict(co2=1250))
        self.assert_states(air=Air.POOR_VENTILATION)
        self.run_for(120, n2=dict(co2=1100))  # Below the alarm level, not recovered
        self.assert_states(air=Air.POOR_VENTILATION)
        self.run_for(61, n2=dict(co2=950))  # Exit (Week 6 feedback)
        self.assert_states(air=Air.NORMAL)

    def test_warming_up_is_unknown(self):
        self.run_for(5, **self.every(co2_valid=False))
        self.assert_states(air=Air.UNKNOWN)
        self.assertIsNone(self.engine.state()["zones"][0]["co2_ppm"])

    def test_temperature_out_of_range_and_back(self):
        self.run_for(30)
        self.run_for(61, **self.every(temp=29.0))
        self.assert_states(comfort=Comfort.OUT_OF_RANGE)
        self.assertEqual(self.engine.state()["comfort_reasons"], ["too warm"])
        self.run_for(120, **self.every(temp=27.8))  # Inside, but within the hysteresis
        self.assert_states(comfort=Comfort.OUT_OF_RANGE)
        self.run_for(61, **self.every(temp=26.0))
        self.assert_states(comfort=Comfort.COMFORTABLE)
        self.assertEqual(self.engine.state()["comfort_reasons"], [])

    def test_humidity_out_of_range(self):
        self.run_for(30)
        self.run_for(61, **self.every(humidity=80.0))
        self.assert_states(comfort=Comfort.OUT_OF_RANGE)
        self.assertIn("too humid", self.engine.state()["comfort_reasons"][0])

    def test_regions_are_independent(self):
        self.run_for(30)
        self.run_for(70, **{f"n{n}": dict(probs=SPEECH if n == 1 else QUIET, pir=20,
                                          co2=1300, temp=29.0) for n in ALL})
        self.assert_states(Activity.FOCUSED_LECTURE, Air.POOR_VENTILATION, Comfort.OUT_OF_RANGE)


class Configuration(unittest.TestCase):
    def write(self, data):
        path = Path(tempfile.mkdtemp()) / "fusion.json"
        path.write_text(json.dumps(data))
        return path

    def test_json_overrides(self):
        cfg = FusionConfig.from_json(self.write(
            {"zones": {"1": "Front", "5": "Back"}, "front_zones": ["Front"],
             "mode": "discussion", "co2_poor_ppm": 1500}))
        self.assertEqual(cfg.zones, {1: "Front", 5: "Back"})
        self.assertEqual((cfg.front_zones, cfg.mode, cfg.co2_poor_ppm),
                         (("Front",), p.Mode.DISCUSSION, 1500))
        self.assertEqual(cfg.co2_recovered_ppm, 1000)  # Default kept

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            FusionConfig.from_json(self.write({"co2_poor_pmm": 1500}))

    def test_unmapped_node_ignored(self):
        engine = FusionEngine()
        engine.add(7, telemetry(probs=SPEECH), 1.0)
        engine.evaluate(1.0, online={7})
        self.assertTrue(all(z["state"] == "NO_DATA" for z in engine.state()["zones"]))


if __name__ == "__main__":
    unittest.main()
