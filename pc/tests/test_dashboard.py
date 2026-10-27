"""Tests for pc/mosaic/dashboard.py.

Run from the pc/ folder:  python -m unittest -v
"""

import io
import json
import time
import unittest
import urllib.error
import urllib.request

from mosaic import protocol as p
from mosaic.dashboard import Dashboard, start_http
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
            p.AudioWindow(100, p.AudioClass.BACKGROUND_NOISE, (90, 5, 3, 2)),
            p.AudioWindow(100, p.AudioClass.LECTURER_SPEECH, (5, 80, 10, 5)))))
        audio = self.dashboard.state()["nodes"][0]["telemetry"]["audio"]
        self.assertEqual(audio, {"class": "lecturer_speech", "confidence": 80,
                                 "probs": [5, 80, 10, 5]})

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


if __name__ == "__main__":
    unittest.main()
