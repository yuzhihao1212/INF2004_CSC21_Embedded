import unittest
from mosaic.integration_check import check_state


class IntegrationCheck(unittest.TestCase):
    def node(self, **changes):
        node = {"id": 1, "status": "online", "simulated": False,
                "telemetry": {"config_version": 2, "pir_pct": 0},
                "config": {"version": 2, "state": "applied"}}
        node.update(changes)
        return node

    def test_real_node_config_confirmed(self):
        errors, _ = check_state({"nodes": [self.node()]}, [1], require_config=True)
        self.assertEqual(errors, [])

    def test_missing_second_node_and_simulator_are_not_hardware_pass(self):
        errors, _ = check_state({"nodes": [self.node(simulated=True)]}, [1, 2])
        self.assertEqual(len(errors), 2)

    def test_queued_config_is_not_success(self):
        errors, _ = check_state({"nodes": [self.node(config={"version": 3, "state": "sending"})]},
                                [1], require_config=True)
        self.assertEqual(len(errors), 1)

    def test_absent_audio_and_invalid_sensors_fail_only_requested_checks(self):
        state = {"nodes": [self.node()]}
        self.assertEqual(check_state(state, [1])[0], [])
        errors, _ = check_state(state, [1], require_audio=True, require_sensors=True)
        self.assertEqual(len(errors), 2)

    def test_offline_is_failure_even_with_old_telemetry(self):
        self.assertEqual(len(check_state({"nodes": [self.node(status="offline")]}, [1])[0]), 1)
