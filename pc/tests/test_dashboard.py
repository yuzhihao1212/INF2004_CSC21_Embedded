"""Tests for pc/mosaic/dashboard.py.

Run from the pc/ folder:  python -m unittest -v
"""

import io
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from mosaic import protocol as p
from mosaic.dashboard import Dashboard, start_http
from mosaic.fusion import FusionConfig, FusionEngine
from mosaic.gateway import GatewayServer

NODE_ADDR = ("192.168.1.21", p.PORT_CONFIG)


def telemetry(node_id=1, seq=0, **fields):
    return p.encode(p.Header(p.MsgType.TELEMETRY, node_id, seq, seq * 1000), p.Telemetry(**fields))


class DashboardState(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO())
        self.addCleanup(self.server.close)
        self.dashboard = Dashboard(self.server)

    def receive(self, data):
        self.server._received(data, NODE_ADDR, time.monotonic())

    def test_valid_and_invalid_fields(self):
        self.receive(telemetry(
            temperature_x10=245, humidity_x10=610, co2_ppm=650, pir_active_pct=40,
            valid_flags=p.Valid.TEMP_HUM | p.Valid.CO2 | p.Valid.PIR, wifi_rssi_dbm=-60))
        self.receive(telemetry(node_id=2, co2_ppm=999, valid_flags=p.Valid.CO2_WARMUP))
        nodes = self.dashboard.state()["nodes"]
        self.assertEqual([n["id"] for n in nodes], [1, 2])

        one = nodes[0]["telemetry"]
        self.assertEqual((one["temperature_c"], one["co2_ppm"], one["pir_pct"]), (24.5, 650, 40))
        self.assertIsNone(one["audio"])
        self.assertEqual(nodes[0]["status"], "online")

        two = nodes[1]["telemetry"]
        self.assertIsNone(two["co2_ppm"])  # Not valid while warming up, whatever was sent
        self.assertTrue(two["co2_warmup"])
        self.assertIsNone(two["temperature_c"])

    def test_latest_audio_window_shown(self):
        self.receive(telemetry(audio=(
            p.AudioWindow(100, p.AudioClass.BACKGROUND_NOISE, (90, 8, 0, 2)),
            p.AudioWindow(100, p.AudioClass.SPEECH, (5, 90, 0, 5)))))
        audio = self.dashboard.state()["nodes"][0]["telemetry"]["audio"]
        self.assertEqual(audio, {"class": "speech", "confidence": 90,
                                 "probs": [5, 90, 0, 5], "rms": 6.25})

    def test_history_keeps_window(self):
        dashboard = Dashboard(self.server, history_s=0.05)
        self.receive(telemetry(co2_ppm=600, valid_flags=p.Valid.CO2))
        time.sleep(0.1)
        self.receive(telemetry(seq=1, co2_ppm=610, valid_flags=p.Valid.CO2))
        history = dashboard.state()["nodes"][0]["history"]
        self.assertEqual([point[3] for point in history], [610])

    def test_simulated_source(self):
        self.assertEqual(self.dashboard.state()["source"], "none")
        self.receive(telemetry())  # From NODE_ADDR, a LAN address
        self.assertEqual(self.dashboard.state()["source"], "sensors")
        self.server._received(telemetry(node_id=2), ("127.0.0.1", 5006), time.monotonic())
        state = self.dashboard.state()
        self.assertEqual(state["source"], "mixed")
        self.assertEqual([n["simulated"] for n in state["nodes"]], [False, True])

    def test_simulation_phase(self):
        self.assertIsNone(self.dashboard.state()["simulation"])  # Real sensors only: no strip
        self.dashboard.simulating(2, None, 100.0)
        self.assertEqual(self.dashboard.simulation(105.0), {"nodes": 2, "scenario": None})

        self.dashboard.simulating(4, "lecture", 100.0)  # Phases: 40 s, 120 s, 200 s, 90 s
        sim = self.dashboard.simulation(100.0 + 40 + 30)
        self.assertEqual((sim["phase"], sim["left_s"], sim["finished"]), (1, 90.0, False))
        self.assertEqual(sim["label"], "Lecturer teaching, students seated")
        self.assertEqual([ph["seconds"] for ph in sim["phases"]], [40, 120, 200, 90])
        done = self.dashboard.simulation(100.0 + 450 + 10)  # Past the end: last phase holds
        self.assertEqual((done["phase"], done["left_s"], done["finished"]), (3, 0.0, True))

    def test_state_is_json(self):
        self.receive(telemetry(valid_flags=p.Valid.TEMP_HUM, temperature_x10=200))
        json.dumps(self.dashboard.state())


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO())
        cls.httpd = start_http(Dashboard(cls.server), "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server.close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=2) as r:
            return r.status, r.headers["Content-Type"], r.read()

    def test_api_state(self):
        status, ctype, body = self.get("/api/state")
        self.assertEqual((status, ctype), (200, "application/json"))
        self.assertEqual(json.loads(body)["nodes"], [])

    def test_page_and_assets(self):
        for path, ctype in [("/", "text/html"), ("/app.js", "text/javascript"),
                            ("/style.css", "text/css")]:
            with self.subTest(path):
                status, got, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertTrue(got.startswith(ctype))
                self.assertTrue(body)

    def test_no_files_outside_web(self):
        for path in ["/../dashboard.py", "/%2e%2e/dashboard.py", "/missing.js", "/../__init__.py"]:
            with self.subTest(path), self.assertRaises(urllib.error.HTTPError) as err:
                self.get(path)
            self.assertEqual(err.exception.code, 404)
            err.exception.close()



class ConfigApi(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO())
        self.httpd = start_http(Dashboard(self.server), "127.0.0.1", 0)
        self.addCleanup(self.server.close)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/nodes/%s/config"
        self.server._received(telemetry(config_version=3), NODE_ADDR, time.monotonic())

    def post(self, node, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            with urllib.request.urlopen(self.url % node, data=data, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_post_starts_delivery(self):
        status, body = self.post(1, {"report_interval_ms": 500, "mode": "discussion"})
        self.assertEqual((status, body), (202, {"config_version": 4}))  # Above the reported 3
        with self.server.lock:
            config = self.server.gateway.nodes[1].config.config
        self.assertEqual((config.report_interval_ms, config.mode), (500, p.Mode.DISCUSSION))
        state = Dashboard(self.server).state()["nodes"][0]["config"]
        self.assertEqual((state["version"], state["state"], state["mode"]),
                         (4, "sending", "DISCUSSION"))

    def test_bad_requests(self):
        cases = [
            (1, {"report_interval_ms": 50}, 400),     # Out of range
            (1, {"report_interval_ms": 1.5}, 400),    # Not an integer
            (1, {"mode": "party"}, 400),
            (1, {"config_version": 9}, 400),          # The PC picks versions
            (1, {"colour": 1}, 400),
            (1, {}, 400),
            (1, b"not json", 400),
            (5, {"report_interval_ms": 500}, 404),    # Node never reported
        ]
        for node, body, code in cases:
            with self.subTest(body=body):
                status, reply = self.post(node, body)
                self.assertEqual(status, code)
                self.assertIn("error", reply)
        with self.server.lock:
            self.assertIsNone(self.server.gateway.nodes[1].config)


class ModeApi(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO(),
                                    fusion=FusionEngine())
        self.dashboard = Dashboard(self.server)
        self.httpd = start_http(self.dashboard, "127.0.0.1", 0)
        self.addCleanup(self.server.close)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/mode"
        for node_id in (1, 2):
            self.server._received(telemetry(node_id=node_id), NODE_ADDR, time.monotonic())

    def post(self, body):
        try:
            with urllib.request.urlopen(self.url, data=json.dumps(body).encode(), timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_mode_switches_fusion_and_configures_nodes(self):
        self.assertEqual(self.post({"mode": "DISCUSSION"}),
                         (202, {"mode": "DISCUSSION", "nodes": [1, 2]}))
        self.assertEqual(self.server.fusion.mode, p.Mode.DISCUSSION)
        for node in self.server.gateway.nodes.values():
            self.assertEqual(node.config.config.mode, p.Mode.DISCUSSION)
        self.server.poll(timeout=0)  # Evaluates fusion
        classroom = self.dashboard.state()["classroom"]
        self.assertEqual((classroom["mode"], classroom["activity"]), ("DISCUSSION", "UNKNOWN"))
        self.assertEqual([z["zone"] for z in classroom["zones"]], ["A", "B", "C", "D"])
        self.assertEqual([z["status"] for z in classroom["zones"]], ["ONLINE", "ONLINE", "OFFLINE", "OFFLINE"])

    def test_bad_mode(self):
        for body in [{"mode": "party"}, {"mode": 7}, {"mode": "LECTURE", "x": 1}, {}]:
            with self.subTest(body=body):
                status, reply = self.post(body)
                self.assertEqual(status, 400)
                self.assertIn("error", reply)
        self.assertEqual(self.server.fusion.mode, p.Mode.LECTURE)

    def test_zone_map_api_shape_and_decimal_display_boundary(self):
        self.server.fusion = FusionEngine(FusionConfig(zone_dwell_ms=0))
        now = time.monotonic()
        self.server._received(telemetry(node_id=1, seq=1, temperature_x10=245,
            humidity_x10=615, co2_ppm=900, pir_active_pct=20,
            valid_flags=p.Valid.TEMP_HUM | p.Valid.CO2 | p.Valid.PIR,
            audio=(p.AudioWindow(160, p.AudioClass.SPEECH, (5, 90, 0, 5)),)), NODE_ADDR, now)
        with urllib.request.urlopen(self.url.replace('/api/mode', '/api/state'), timeout=2) as response:
            classroom = json.load(response)['classroom']
        self.assertEqual(classroom['zone_layout'], {'A': [0, 0], 'B': [1, 0], 'C': [2, 0], 'D': [3, 0]})
        a, _, c, _ = classroom['zones']
        self.assertEqual((a['state'], a['air'], a['comfort']), ('LECTURER', 'FAIR', 'COMFORTABLE'))
        self.assertEqual((a['temperature_x10'], a['temperature_c'], a['humidity_pct']), (245, 24.5, 61.5))
        self.assertEqual((a['node_id'], a['layout'], a['reference_zone'], a['motion_pct']), (1, [0, 0], True, 20))
        self.assertEqual((c['state'], c['status'], c['co2_ppm']), ('NO_DATA', 'OFFLINE', None))
        self.assertIsInstance(classroom['confidence_pct'], int)


class LoudnessApi(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "loud.json"
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO(), fusion=FusionEngine())
        self.addCleanup(self.server.close)

    def start(self):
        self.dashboard = Dashboard(self.server, loud_levels_path=self.path)
        self.httpd = start_http(self.dashboard, "127.0.0.1", 0)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def post(self, body, path="/api/loudness/capture"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            with urllib.request.urlopen(self.base + path, data=data, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_capture_saves_and_clear_removes(self):
        self.start()
        self.assertEqual(self.post({"zone": "C"})[0], 202)
        fusion = self.server.fusion
        self.assertTrue(fusion.state()["zones"][2]["loud"]["capturing"])
        # Finish a capture directly, as if 5 s of loud windows had arrived.
        fusion.config.loud_levels_x16["C"] = 2400
        self.dashboard.state()
        self.assertEqual(json.loads(self.path.read_text()), {"version": 1, "levels_x16": {"C": 2400}})
        self.assertEqual(self.post({"zone": "C"}, "/api/loudness/clear")[0], 202)
        self.assertEqual(json.loads(self.path.read_text())["levels_x16"], {})

    def test_bad_requests(self):
        self.start()
        for body in (b"not json", {}, {"zone": 3}, {"zone": "C", "extra": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body)[0], 400)
        for zone in ("A", "missing"):
            self.assertEqual(self.post({"zone": zone})[0], 404)
        self.server.fusion = None
        self.assertEqual(self.post({"zone": "C"})[0], 409)

    def test_loads_saved_levels_for_student_zones_only(self):
        self.path.write_text(json.dumps({"version": 1, "levels_x16": {"A": 9, "C": 2400, "Z": 5, "D": "x"}}))
        self.start()
        self.assertEqual(self.server.fusion.config.loud_levels_x16, {"C": 2400})
        self.path.write_text("[]")
        with self.assertRaises(ValueError):
            Dashboard(self.server, loud_levels_path=self.path)

    def test_state_has_loudness_setup(self):
        self.start()
        state = self.dashboard.state()
        self.assertEqual(state["feedback"]["loudness"]["state"], "not_set_up")
        self.assertEqual([a["zone"] for a in state["feedback"]["loudness"]["areas"]], ["B", "C", "D"])


class CalibrationApi(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO(), fusion=FusionEngine())
        self.dashboard = Dashboard(self.server)
        self.httpd = start_http(self.dashboard, "127.0.0.1", 0)
        self.addCleanup(self.server.close)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def post(self, body=b"{}", path="/api/calibrate"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            with urllib.request.urlopen(self.base + path, data=data, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_calibrate_all_restart_one_and_reset(self):
        code, reply = self.post()
        self.assertEqual(code, 202)
        zones = reply["reference"]["zones"]
        self.assertEqual(set(zones), {"B", "C", "D"})
        self.assertTrue(all(z["state"] == "CALIBRATING" for z in zones.values()))
        self.assertEqual(self.post({"zone": "C"})[0], 202)
        code, reply = self.post({"zone": "C"}, "/api/calibrate/reset")
        self.assertEqual(code, 202)
        self.assertEqual(reply["reference"]["zones"]["C"]["state"], "UNCALIBRATED")
        self.assertEqual(reply["reference"]["zones"]["B"]["state"], "CALIBRATING")
        self.assertEqual(self.post(path="/api/calibrate/reset")[0], 202)
        self.assertEqual(self.server.gateway.nodes, {})  # No node commands or relays.

    def test_invalid_requests_and_unknown_zone(self):
        for body in (b"not json", b"\xff", [], {"zone": None}, {"zone": 3}, {"extra": 1}):
            with self.subTest(body=body):
                code, reply = self.post(body)
                self.assertEqual(code, 400)
                self.assertIn("error", reply)
        for zone in ("A", "missing"):
            self.assertEqual(self.post({"zone": zone})[0], 404)
        self.assertEqual(self.post(b"x" * 4097)[0], 413)

    def test_disabled_or_absent_fusion(self):
        for fusion in (None, FusionEngine(FusionConfig(reference_zone=None)),
                       FusionEngine(FusionConfig(zones={3: "C"}))):
            self.server.fusion = fusion
            self.assertEqual(self.post()[0], 409)

    def test_applied_report_interval_is_forwarded_to_fusion(self):
        now = time.monotonic()
        self.server._received(telemetry(node_id=3), NODE_ADDR, now)
        config = self.server.set_config(3, report_interval_ms=2000)
        self.server._received(telemetry(node_id=3, seq=1, config_version=config.config_version,
            audio=(p.AudioWindow(160, p.AudioClass.UNKNOWN, (5, 90, 0, 5)),)), NODE_ADDR, now + 1)
        self.assertEqual(self.server.gateway.nodes[3].report_interval_ms, 2000)
        self.assertEqual(self.server.fusion.state()['zones'][2]['report_interval_ms'], 2000)
        self.assertEqual(self.server.fusion.state()['reference']['zones']['C']['freshness_ms'], 2750)

    def test_state_contains_per_zone_reference_status_and_levels(self):
        now = time.monotonic()
        self.server.fusion.calibrate(now - 20)
        for i in range(20):
            received = now - 9.5 + i * 0.5
            for node in (1, 2, 3, 4):
                level = (20 + 4 * i) * (1 if node == 1 else 0.5)
                data = telemetry(node_id=node, seq=i, audio_window_seq=i + 1,
                                 audio=(p.AudioWindow(round(level * 16), p.AudioClass.UNKNOWN,
                                                      (5, 90, 0, 5)),))
                self.server._received(data, NODE_ADDR, received)
        self.server.fusion.evaluate(now, {1, 2, 3, 4})
        with urllib.request.urlopen(self.base + "/api/state", timeout=2) as r:
            state = json.loads(r.read())["classroom"]
        c = state["reference"]["zones"]["C"]
        self.assertEqual(c["state"], "QUIET")
        self.assertEqual(c["pairs_collected"], 20)
        self.assertAlmostEqual(c["gain"], 0.25)
        self.assertEqual(c["expected_rms"], c["student_rms"])
        self.assertGreater(c["threshold"], c["student_rms"])
        self.assertEqual(c["smoothed_state"], "UNKNOWN")  # Only the baseline-ready window so far.
        self.assertEqual(c["known_windows"], 1)
        self.assertEqual(c["talking_fraction"], 0)
        self.assertEqual(c["decision_source"], "probabilities")
        self.assertEqual(next(z for z in state["zones"] if z["zone"] == "C")["reference"], c)


if __name__ == "__main__":
    unittest.main()
