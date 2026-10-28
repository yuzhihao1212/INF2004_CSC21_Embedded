"""Reference comparison with synthetic 500 ms evidence; no sleeping or sockets."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from mosaic import protocol as p
from mosaic.fusion import FusionConfig, FusionEngine
from mosaic.reference import ReferenceConfig, ReferenceFusion

SPEECH = (5, 85, 5, 5)
OTHER_SPEECH = (5, 5, 85, 5)
NOISE = (90, 3, 2, 5)


def window(rms, probs=SPEECH):
    return p.AudioWindow(round(rms * 16), p.AudioClass.UNKNOWN, probs)


class Reference(unittest.TestCase):
    def setUp(self):
        self.ref = ReferenceFusion({1: "A", 3: "C"})
        self.now = 0.0
        self.seq = {1: 0, 3: 0}

    @property
    def status(self):
        return self.ref.state()["zones"]["C"]

    def send(self, node, rms, now, probs=SPEECH, count=1, **kwargs):
        self.seq[node] = (self.seq[node] + count) % 65536
        telemetry = p.Telemetry(audio_window_seq=self.seq[node],
                                audio=tuple(window(rms, probs) for _ in range(count)), **kwargs)
        self.ref.add(node, telemetry, now)
        return telemetry

    def pair(self, reference=40, student=20, ref_probs=SPEECH, student_probs=SPEECH,
             offset=0.0, reverse=False):
        self.now += 0.5
        inputs = [(1, reference, self.now, ref_probs),
                  (3, student, self.now + offset, student_probs)]
        for node, rms, now, probs in reversed(inputs) if reverse else inputs:
            self.send(node, rms, now, probs)
        return self.status

    def calibrate(self, background=0.0):
        self.ref.calibrate(self.now)
        for i in range(20):
            rms = 20 + 4 * i
            self.pair(rms, math.sqrt(0.25 * rms * rms + background))
        self.assertIsNotNone(self.status["gain"])

    def talking(self):
        self.calibrate()
        self.pair(student=80)
        self.pair(student=80)
        self.assertEqual(self.status["state"], "TALKING")

    def test_operator_starts_and_resets_calibration(self):
        self.pair()
        self.assertEqual(self.status["state"], "UNCALIBRATED")
        self.assertEqual(self.status["pairs_collected"], 0)
        self.calibrate()
        self.ref.calibrate(self.now, "C")
        self.assertEqual((self.status["state"], self.status["pairs_collected"]), ("CALIBRATING", 0))
        self.assertIsNone(self.status["gain"])
        self.ref.reset("C")
        self.assertEqual(self.status["state"], "UNCALIBRATED")

    def test_twenty_pair_minimum_and_known_power_fit(self):
        self.ref.calibrate(0)
        for i in range(19):
            self.pair(20 + 4 * i, 10 + 2 * i)
        self.assertEqual(self.status["pairs_collected"], 19)
        self.assertIsNone(self.status["gain"])
        self.pair(96, 48)
        self.assertEqual(self.status["state"], "QUIET")
        self.assertAlmostEqual(self.status["gain"], 0.25)
        self.assertAlmostEqual(self.status["background_power"], 0)
        self.assertAlmostEqual(self.status["upper_residual"], 0)
        self.pair(100, 300)  # Baseline stays frozen, rather than learning student speech.
        self.assertAlmostEqual(self.status["gain"], 0.25)
        self.assertEqual(self.status["pairs_collected"], 20)

    def test_background_recovered_from_quantised_rms(self):
        self.calibrate(background=16)
        self.assertAlmostEqual(self.status["gain"], 0.25, delta=0.002)
        self.assertAlmostEqual(self.status["background_power"], 16, delta=2)

    def test_threshold_formula(self):
        self.calibrate(background=16)
        s = self.pair(40, 60)
        power = s["gain"] * 40 ** 2 + s["background_power"]
        self.assertAlmostEqual(s["expected_rms"], math.sqrt(power))
        self.assertAlmostEqual(s["threshold"], math.sqrt(power + s["upper_residual"]) * 1.25 + 4)

    def test_nearest_rank_positive_residual_percentile(self):
        self.ref.calibrate(0)
        for i in range(20):
            r = 20 + i * 4
            self.pair(r, math.sqrt(0.25 * r * r + (200 if i == 19 else i % 3)))
        s = self.status
        errors = sorted(max(0, y - (s["gain"] * x + s["background_power"]))
                        for x, y in self.ref.students["C"].powers)
        self.assertAlmostEqual(s["upper_residual"], errors[18])
        self.assertLess(errors[18], errors[19])

    def test_negative_intercept_refits_through_origin(self):
        self.ref.calibrate(0)
        for i in range(20):
            r = 20 + i * 4
            self.pair(r, math.sqrt(0.25 * r * r - 25))
        pairs = self.ref.students["C"].powers
        self.assertEqual(self.status["background_power"], 0)
        self.assertAlmostEqual(self.status["gain"], sum(x * y for x, y in pairs) / sum(x * x for x, y in pairs))

    def test_negative_gain_clamped(self):
        self.ref.calibrate(0)
        for i in range(20):
            self.pair(20 + i, 50 - i)
        self.assertEqual(self.status["gain"], 0)
        self.assertGreater(self.status["background_power"], 0)

    def test_constant_reference_requires_level_variation_and_caps_pairs(self):
        self.ref.calibrate(0)
        for _ in range(70):
            self.pair(40, 20)
        self.assertEqual(self.status["state"], "CALIBRATING")
        self.assertEqual(self.status["pairs_collected"], 64)
        self.assertIsNone(self.status["gain"])

    def test_calibration_requires_reference_speech_and_level(self):
        self.ref.calibrate(0)
        self.pair(ref_probs=NOISE)
        self.pair(reference=3)
        self.assertEqual(self.status["pairs_collected"], 0)
        self.pair(student_probs=NOISE)
        self.assertEqual(self.status["pairs_collected"], 1)

    def test_pairing_inclusive_tolerance_and_reverse_arrival(self):
        self.ref.calibrate(0)
        self.pair(offset=0.25)
        self.pair(offset=0.25, reverse=True)
        self.assertEqual(self.status["pairs_collected"], 2)

    def test_pairing_outside_tolerance(self):
        self.ref.calibrate(0)
        self.pair(offset=0.25001)
        self.assertEqual(self.status["pairs_collected"], 0)
        self.assertEqual(self.status["state"], "UNKNOWN")

    def test_pairing_tolerance_configurable(self):
        self.ref = ReferenceFusion({1: "A", 3: "C"}, config=ReferenceConfig(pair_tolerance_s=0.1))
        self.ref.calibrate(0)
        self.pair(offset=0.15)
        self.assertEqual(self.status["pairs_collected"], 0)

    def test_two_window_batch_timing_and_onset(self):
        self.calibrate()
        now = self.now + 1
        self.send(3, 80, now, count=2)
        self.assertEqual([w.time for w in self.ref.students["C"].windows], [now - 0.5, now])
        self.send(1, 40, now, count=2)
        self.assertEqual(self.status["state"], "TALKING")

    def test_overlapping_reports_only_collect_new_windows(self):
        self.ref.calibrate(0)
        for node in (1, 3):
            self.send(node, 40 if node == 1 else 20, 1, count=2)
        self.assertEqual(self.status["pairs_collected"], 2)
        for node in (1, 3):
            self.seq[node] += 1
            self.ref.add(node, p.Telemetry(audio_window_seq=self.seq[node],
                                          audio=(window(40 if node == 1 else 20),) * 2), 1.5)
        self.assertEqual(self.status["pairs_collected"], 3)

    def test_operator_start_does_not_reuse_pre_start_window(self):
        self.ref.calibrate(0.75)
        for node in (1, 3):
            self.send(node, 40 if node == 1 else 20, 1, count=2)
        self.assertEqual(self.status["pairs_collected"], 1)

    def test_expired_unmatched_windows_are_not_calibration_pairs(self):
        self.ref.calibrate(0)
        self.send(1, 40, 1)
        self.send(3, 20, 3)
        self.assertEqual(self.status["pairs_collected"], 0)
        self.assertEqual(self.status["state"], "UNKNOWN")

    def test_json_config_exposes_reference_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fusion.json"
            path.write_text(json.dumps({"reference_zone": "B", "reference_relative_margin": 0.5,
                                        "reference_pair_tolerance_s": 0.1}))
            config = FusionConfig.from_json(path)
            engine = FusionEngine(config)
            self.assertEqual(engine.reference.reference_node, 2)
            self.assertEqual(engine.reference.config.relative_margin, 0.5)
            self.assertEqual(engine.reference.config.pair_tolerance_s, 0.1)

    def test_two_window_onset_hold_resume_and_release(self):
        self.calibrate()
        self.assertEqual(self.pair(student=80)["state"], "PENDING")
        self.assertEqual(self.pair(student=80)["state"], "TALKING")
        self.assertTrue(self.pair(student=20)["hold"])
        self.assertEqual(self.status["state"], "TALKING")
        self.assertFalse(self.pair(student=80)["hold"])
        self.assertEqual(self.status["state"], "TALKING")
        self.pair(student=20)
        self.assertEqual(self.pair(student=20)["state"], "QUIET")
        self.assertEqual(self.pair(student=80)["state"], "PENDING")

    def test_weak_window_interrupts_pending_and_loud_noise_is_not_speech(self):
        self.calibrate()
        self.pair(student=80)
        self.assertEqual(self.pair(student=80, student_probs=NOISE)["state"], "QUIET")
        self.assertEqual(self.pair(student=80)["state"], "PENDING")

    def test_speech_evidence_independent_of_lecturer_student_class_split(self):
        self.calibrate()
        self.pair(student=80, student_probs=OTHER_SPEECH)
        self.assertEqual(self.pair(student=80, student_probs=SPEECH)["state"], "TALKING")

    def test_valid_silent_reference_does_not_disable_local_speech(self):
        self.calibrate()
        self.pair(reference=0, student=80, ref_probs=NOISE)
        self.assertEqual(self.pair(reference=0, student=80, ref_probs=NOISE)["state"], "TALKING")

    def test_low_level_resets_immediately_like_c(self):
        self.talking()
        self.assertEqual(self.pair(student=0)["state"], "QUIET")
        self.assertFalse(self.status["hold"])

    def test_threshold_is_strictly_greater(self):
        self.calibrate()
        self.pair(40, 29)  # Exact threshold = 20 * 1.25 + 4.
        self.assertEqual(self.status["state"], "QUIET")

    def test_offline_and_stale_audio_reset_persistence(self):
        self.talking()
        for online in ({1}, {3}, set()):
            self.ref.evaluate(self.now, online)
            self.assertEqual(self.status["state"], "UNKNOWN")
        self.assertIsNotNone(self.status["gain"])
        self.assertEqual(self.pair(student=80)["state"], "PENDING")
        self.ref.evaluate(self.now + 1.5001, {1, 3})
        self.assertEqual(self.status["state"], "UNKNOWN")
        self.assertIsNone(self.status["threshold"])

    def test_sequence_gap_resets_and_does_not_fall_back(self):
        self.talking()
        self.seq[3] += 2
        self.send(3, 80, self.now + 0.5)
        self.assertEqual(self.status["state"], "UNKNOWN")
        self.assertFalse(self.ref.talking("C"))

    def test_receive_time_gap_resets(self):
        self.talking()
        self.now += 1
        self.pair(student=80)
        # The received strong window now starts a NEW onset, rather than being
        # thrown away with the missing windows. It cannot retain old TALKING.
        self.assertEqual(self.status["state"], "PENDING")

    def test_two_second_reports_reset_persistence_but_process_received_windows(self):
        self.calibrate()
        gain = self.status["gain"]
        for _ in range(4):
            self.now += 2
            for node in (1, 3):
                # Four audio windows completed; only the newest two fit v2.
                self.seq[node] += 4
                self.ref.add(node, p.Telemetry(audio_window_seq=self.seq[node],
                    audio=(window(40 if node == 1 else 80),) * 2), self.now)
            self.ref.evaluate(self.now, {1, 3})
            self.assertEqual(self.status["gain"], gain)
            self.assertEqual(self.status["state"], "TALKING")

    def test_duplicate_and_out_of_order_do_not_collect_or_latch(self):
        self.talking()
        for seq in (self.seq[3], self.seq[3] - 1):
            self.ref.add(3, p.Telemetry(audio_window_seq=seq, audio=(window(80),)), self.now + 0.1)
            self.assertEqual(self.status["state"], "UNKNOWN")
            self.assertEqual(self.status["pairs_collected"], 20)

    def test_wraparound_is_contiguous(self):
        self.seq = {1: 65534, 3: 65534}
        self.ref.calibrate(0)
        self.pair()
        self.pair()
        self.assertEqual(self.status["pairs_collected"], 2)

    def test_reboot_restarts_sequence_tracking_without_restoring_alert(self):
        self.talking()
        self.ref.add(3, p.Telemetry(audio_window_seq=1, audio=(window(80),)), self.now + 0.5, reboot=True)
        self.assertEqual(self.status["state"], "UNKNOWN")
        self.assertEqual(self.ref._streams[3][0], 1)

    def test_invalid_audio_and_new_overrun_reset(self):
        self.talking()
        for w in (window(5000), window(80, (0, 0, 0, 0)), window(80, (101, 0, 0, 0))):
            self.seq[3] += 1
            self.now += 0.5
            self.ref.add(3, p.Telemetry(audio_window_seq=self.seq[3], audio=(w,)), self.now)
            self.assertEqual(self.status["state"], "UNKNOWN")
        self.send(3, 80, self.now + 0.5, audio_overruns=1)
        self.assertEqual(self.status["state"], "UNKNOWN")
        self.assertIn("overrun", self.status["reason"])

    def test_empty_audio_is_unknown(self):
        self.talking()
        self.ref.add(1, p.Telemetry(audio_window_seq=self.seq[1]), self.now + 0.5)
        self.assertEqual(self.status["state"], "UNKNOWN")

    def test_json_round_trip_restores_only_baseline(self):
        self.talking()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.json"
            self.ref.save(path)
            restored = ReferenceFusion({1: "A", 3: "C"})
            restored.load(path)
            s = restored.state()["zones"]["C"]
            self.assertEqual(s["gain"], self.status["gain"])
            self.assertEqual(s["pairs_collected"], 20)
            self.assertEqual(s["state"], "UNKNOWN")
            self.assertIsNone(s["threshold"])
            self.assertFalse(s["hold"])

    def test_invalid_json_is_atomic(self):
        self.calibrate()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.json"
            self.ref.save(path)
            original = json.loads(path.read_text())
            for key, value in (("gain", -1), ("background_power", float("nan")),
                               ("pairs_collected", 19), ("upper_residual", True)):
                data = json.loads(json.dumps(original))
                data["models"]["C"][key] = value
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    self.ref.load(path)
                self.assertAlmostEqual(self.status["gain"], 0.25)
            data = original | {"reference_zone": "B"}
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                self.ref.load(path)

    def test_invalid_reference_settings(self):
        for kwargs in ({"min_pairs": 19}, {"max_pairs": 65}, {"max_gap_s": 0.1},
                       {"relative_margin": -1}, {"student_speech_pct": 101},
                       {"max_age_s": float("nan")}, {"pair_tolerance_s": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ReferenceConfig(**kwargs)


class FusionReference(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine(FusionConfig(occupied_after_s=0, activity_dwell_s=0,
                                                chatter_after_s=1, audio_smooth_s=0.5,
                                                reference_min_known_windows=1))
        self.engine.calibrate(0)
        self.now, self.seq = 0.0, 0
        for i in range(20):
            self.feed(40 + i * 2)

    def feed(self, reference=60, talking=(), probs=SPEECH, online=None):
        self.now += 0.5
        self.seq += 1
        for node in (1, 2, 3, 4):
            rms = reference if node == 1 else (100 if node in talking else reference * 0.5)
            self.engine.add(node, p.Telemetry(audio_window_seq=self.seq, audio=(window(
                rms, SPEECH if node == 1 else probs),)), self.now)
        self.engine.evaluate(self.now, {1, 2, 3, 4} if online is None else online)

    def test_level_not_classifier_drives_conversation_and_sustained_chatter(self):
        self.feed(probs=OTHER_SPEECH)  # Classifier calls attenuated lecturer speech conversation.
        self.assertEqual(self.engine.activity.state.value, "FOCUSED_LECTURE")
        self.feed(talking=(3,))
        self.feed(talking=(3,))
        self.assertEqual(self.engine.activity.state.value, "NOISE_RISING")
        self.feed(talking=(3,))
        self.feed(talking=(3,))
        self.assertEqual(self.engine.activity.state.value, "SUSTAINED_CHATTER")

    def test_discussion_requires_widespread_student_talking(self):
        self.engine.set_mode(p.Mode.DISCUSSION, self.now)
        self.feed(talking=(3, 4))
        self.feed(talking=(3, 4))
        self.assertEqual(self.engine.activity.state.value, "DISCUSSION")

    def test_reference_offline_falls_back_then_returns_to_known_reference(self):
        for _ in range(22):
            self.feed(probs=OTHER_SPEECH, online={2, 3, 4})
        self.assertEqual(self.engine.reference.state()["zones"]["C"]["state"], "UNKNOWN")
        self.assertIn(self.engine.activity.state.value, ("NOISE_RISING", "SUSTAINED_CHATTER"))
        for _ in range(22):
            self.feed(probs=OTHER_SPEECH)
        self.assertEqual(self.engine.activity.state.value, "FOCUSED_LECTURE")

    def test_gateway_stale_set_expires_reference(self):
        self.feed(talking=(3,))
        self.feed(talking=(3,))
        self.engine.evaluate(self.now, online={1, 2, 4}, stale={3})
        self.assertEqual(self.engine.reference.state()["zones"]["C"]["state"], "UNKNOWN")

    def test_disabled_and_uncalibrated_keep_legacy_rule(self):
        for reference_zone in (None, "A"):
            engine = FusionEngine(FusionConfig(reference_zone=reference_zone, occupied_after_s=0,
                                               activity_dwell_s=0))
            for now in (0, 1):
                engine.add(3, p.Telemetry(audio=(window(100, OTHER_SPEECH),)), now)
                engine.evaluate(now, {3})
            self.assertEqual(engine.activity.state.value, "NOISE_RISING")


class RollingReference(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine(FusionConfig(zones={1: "A", 3: "C"}, front_zones=("A",),
                                                occupied_after_s=0, activity_dwell_s=0))
        self.engine.calibrate(0)
        self.now, self.seq = 0.0, 0
        for i in range(20):
            self.feed(reference=40 + i * 2)

    @property
    def status(self):
        return self.engine.state()["reference"]["zones"]["C"]

    def feed(self, reference=60, local=None, count=1, probs=SPEECH):
        self.now += count * 0.5
        self.seq += count
        for node in (1, 3):
            rms = reference if node == 1 else (reference / 2 if local is None else local)
            self.engine.add(node, p.Telemetry(audio_window_seq=self.seq,
                audio=(window(rms, SPEECH if node == 1 else probs),) * count), self.now)
        self.engine.evaluate(self.now, {1, 3})

    def test_batches_count_each_result_and_evaluation_does_not_invent_windows(self):
        self.assertEqual(self.status["known_windows"], 1)
        self.feed(local=100, count=2)  # PENDING, TALKING: both must be counted.
        self.assertEqual(self.status["known_windows"], 3)
        self.assertAlmostEqual(self.status["talking_fraction"], 1 / 3)
        self.assertEqual(self.status["smoothed_state"], "UNKNOWN")
        self.assertEqual(self.status["decision_source"], "probabilities")
        for _ in range(100):
            self.engine.evaluate(self.now, {1, 3})
        self.assertEqual(self.status["known_windows"], 3)
        self.feed()  # First weak window is HOLD and still TALKING.
        self.assertTrue(self.status["hold"])
        self.assertEqual(self.status["known_windows"], 4)
        self.assertEqual(self.status["talking_fraction"], 0.5)
        self.assertEqual(self.status["smoothed_state"], "TALKING")

    def test_unknown_samples_excluded_then_old_evidence_expires_to_fallback(self):
        self.feed(local=100, count=2)
        self.feed()
        self.engine.add(3, p.Telemetry(audio_window_seq=self.seq), self.now + 0.1)
        self.engine.evaluate(self.now + 0.1, {1, 3})
        self.assertEqual(self.status["state"], "UNKNOWN")  # Raw window result.
        self.assertEqual(self.status["known_windows"], 4)
        self.assertEqual(self.status["talking_fraction"], 0.5)
        self.assertEqual(self.status["smoothed_state"], "TALKING")
        self.engine.evaluate(self.now + 1.6, {1, 3})
        self.assertEqual(self.status["smoothed_state"], "UNKNOWN")
        self.assertEqual(self.status["decision_source"], "probabilities")
        self.engine.evaluate(self.now + 10.1, {1, 3})
        self.assertEqual(self.status["known_windows"], 0)
        self.assertIsNone(self.status["talking_fraction"])

    def test_fraction_is_configurable(self):
        self.engine.config.reference_talking_fraction = 0.75
        self.feed(local=100, count=2)
        self.feed()
        self.assertEqual(self.status["talking_fraction"], 0.5)
        self.assertEqual(self.status["smoothed_state"], "QUIET")

    def test_offline_or_stale_node_forces_fallback_despite_recent_history(self):
        self.feed(local=100, count=2)
        self.feed()
        for online, stale in (({3}, set()), ({3}, {1}), ({1}, {3})):
            self.engine.evaluate(self.now, online, stale)
            self.assertEqual(self.status["smoothed_state"], "UNKNOWN")
            self.assertEqual(self.status["decision_source"], "probabilities")

    def test_calibrate_reset_and_load_clear_old_smoothing_history(self):
        self.feed(local=100, count=2)
        self.feed()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            self.engine.reference.save(path)
            self.engine.reference.load(path)
            self.engine.evaluate(self.now, {1, 3})
            self.assertEqual(self.status["known_windows"], 0)
            self.assertEqual(self.status["smoothed_state"], "UNKNOWN")
        self.feed()
        self.engine.calibrate(self.now)
        self.engine.evaluate(self.now, {1, 3})
        self.assertEqual(self.status["known_windows"], 0)
        self.engine.reset_reference()
        self.engine.evaluate(self.now, {1, 3})
        self.assertEqual(self.status["known_windows"], 0)

    def test_smoothing_config_validation(self):
        for kwargs in ({"reference_talking_fraction": 0}, {"reference_talking_fraction": 1.1},
                       {"reference_talking_fraction": float("nan")},
                       {"reference_talking_fraction": True}, {"reference_min_known_windows": 0},
                       {"reference_min_known_windows": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                FusionConfig(**kwargs)


if __name__ == "__main__":
    unittest.main()
