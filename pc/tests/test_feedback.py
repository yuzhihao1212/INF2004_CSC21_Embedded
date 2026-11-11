"""Plain-language feedback, alerts and the page's accessibility contract
(docs/ui_design.md).

Run from the pc/ folder:  python -m unittest -v
"""

import io
import itertools
import json
import re
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from mosaic import feedback as fb
from mosaic import protocol as p
from mosaic.dashboard import Dashboard, start_http
from mosaic.fusion import Activity, Air, Comfort, FusionEngine, ZoneActivity, ZoneAir
from mosaic.gateway import GatewayServer

ENGINE_WORDS = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b|\b(?:UNKNOWN|NORMAL|EMPTY|QUIET|STALE|OFFLINE|ONLINE)\b")
LAYOUT = {"A": [0, 0], "B": [1, 0], "C": [2, 0], "D": [3, 0]}


def zone(name, node, state="STILL", status="ONLINE", air="GOOD", comfort="COMFORTABLE", **extra):
    return {"zone": name, "node_id": node, "status": status, "state": state, "since_ms": 0,
            "air": air, "comfort": comfort, "layout": list(LAYOUT.get(name, [4, 0])), "reference_zone": name == "A",
            "co2_ppm": 700, "temperature_c": 24.5, "humidity_pct": 55.0, "motion_active": False,
            "motion_pct": 3, **extra}


def classroom(activity="FOCUSED_LECTURE", air="NORMAL", comfort="COMFORTABLE", mode="LECTURE",
              zones=None, reasons=(), now_ms=300000, since_ms=0):
    return {"mode": mode, "activity": activity, "air": air, "comfort": comfort,
            "comfort_reasons": list(reasons), "now_ms": now_ms, "activity_since_ms": since_ms,
            "air_since_ms": 0, "reference": {"enabled": False, "zone": "A", "zones": {}},
            "zones": zones or [zone("A", 1, "LECTURER"), zone("B", 2), zone("C", 3), zone("D", 4)]}


NODES = [{"id": n, "status": "online", "telemetry": {"co2_warmup": False}} for n in (1, 2, 3, 4)]


class Labels(unittest.TestCase):
    def test_every_engine_state_has_a_plain_label(self):
        for enum, table in ((Activity, fb.ACTIVITY), (Air, fb.AIR), (Comfort, fb.COMFORT),
                            (ZoneActivity, fb.ZONE_ACTIVITY), (ZoneAir, fb.ZONE_AIR), (p.Mode, fb.MODE)):
            for member in enum:
                key = member.value if isinstance(member.value, str) else member.name
                with self.subTest(state=key):
                    self.assertIn(key, table)
                    self.assertIsNone(ENGINE_WORDS.search(table[key]))
        self.assertEqual(set(fb.SENSOR), {"ONLINE", "STALE", "OFFLINE"})

    def test_no_engine_name_reaches_the_main_view(self):
        combos = itertools.product(fb.ACTIVITY, fb.AIR, fb.COMFORT, fb.MODE)
        for activity, air, comfort, mode in combos:
            c = classroom(activity, air, comfort, mode, reasons=("too warm",) if comfort == "OUT_OF_RANGE" else ())
            out = fb.describe(c, NODES)
            shown = [out["headline"], out["summary"], out["sensors"]["text"]]
            shown += [t[k] for t in out["tiles"] for k in ("title", "label", "why")]
            shown += [z[m]["label"] for z in out["zones"] for m in ("activity", "air", "comfort", "motion")]
            shown += [z["name"] for z in out["zones"]] + [a["message"] + a["action"] for a in out["alerts_wanted"].values()]
            for text in shown:
                with self.subTest(activity=activity, air=air, comfort=comfort, mode=mode, text=text):
                    self.assertIsNone(ENGINE_WORDS.search(text))

    def test_room_areas(self):
        names = fb.zone_names(classroom()["zones"])
        self.assertEqual(names, {"A": "Lecturer's area", "B": "Front rows", "C": "Middle rows", "D": "Back rows"})
        # A fifth sensor splits the back rows into door and window side.
        five = classroom()["zones"] + [zone("E", 5)]
        five[3]["layout"], five[4]["layout"] = [3, 0], [3, 1]
        self.assertEqual({k: v for k, v in fb.zone_names(five).items() if k in "DE"},
                         {"D": "Back rows, door side", "E": "Back rows, window side"})
        one_row = [dict(zone=z, layout=[0, i]) for i, z in enumerate("ABC")]
        self.assertEqual(fb.zone_names(one_row), {"A": "Seating, door side", "B": "Seating, centre",
                                                  "C": "Seating, window side"})

    def test_checking_instead_of_no_data_while_sensors_work(self):
        out = fb.describe(classroom("UNKNOWN"), NODES)
        self.assertEqual(out["headline"], "Checking the room…")
        self.assertIn("Waiting for enough readings", out["summary"])


class Severity(unittest.TestCase):
    def level(self, activity, mode):
        return fb.describe(classroom(activity, mode=mode), NODES)["tiles"][0]["level"]

    def test_depends_on_class_type(self):
        self.assertEqual(self.level("SUSTAINED_CHATTER", "LECTURE"), fb.ACT_NOW)
        self.assertEqual(self.level("SUSTAINED_CHATTER", "QUIET_WORK"), fb.ACT_NOW)
        self.assertEqual(self.level("NOISE_RISING", "LECTURE"), fb.HEADS_UP)
        self.assertEqual(self.level("DISCUSSION", "DISCUSSION"), fb.FINE)
        self.assertEqual(self.level("FOCUSED_LECTURE", "LECTURE"), fb.FINE)
        self.assertEqual(self.level("FOCUSED_LECTURE", "QUIET_WORK"), fb.HEADS_UP)

    def test_talking_areas_and_duration(self):
        zones = [zone("A", 1, "LECTURER"), zone("B", 2), zone("C", 3, "TALKING"), zone("D", 4, "TALKING")]
        # Chatter escalated 10 s ago, but the areas have talked for 3+ minutes.
        out = fb.describe(classroom("SUSTAINED_CHATTER", zones=zones, now_ms=200000, since_ms=190000), NODES)
        self.assertEqual(out["tiles"][0]["why"], "Talking in the middle rows and the back rows for 3 minutes.")
        self.assertEqual(out["alerts_wanted"]["chatter"]["message"], "Ongoing chatter in the middle rows and the back rows.")

    def test_comfort_direction(self):
        out = fb.describe(classroom(comfort="OUT_OF_RANGE", reasons=("too warm", "too humid")), NODES)
        self.assertEqual(out["tiles"][2]["label"], "Too warm and too humid")
        self.assertEqual(out["tiles"][2]["level"], fb.HEADS_UP)


class CombinedRules(unittest.TestCase):
    def test_chatter_and_stuffy_air_is_one_alert(self):
        out = fb.describe(classroom("SUSTAINED_CHATTER", "POOR_VENTILATION"), NODES)
        self.assertEqual(set(out["alerts_wanted"]), {"chatter_air"})
        self.assertIn("open a door or window", out["alerts_wanted"]["chatter_air"]["action"])

    def test_stuffy_empty_room_is_only_a_heads_up(self):
        out = fb.describe(classroom("EMPTY", "POOR_VENTILATION"), NODES)
        self.assertEqual(out["alerts_wanted"], {})
        self.assertEqual(out["tiles"][1]["level"], fb.HEADS_UP)
        self.assertIn("before the next class", out["tiles"][1]["why"])

    def test_stuffy_occupied_room_alerts(self):
        out = fb.describe(classroom("FOCUSED_LECTURE", "POOR_VENTILATION"), NODES)
        self.assertEqual(set(out["alerts_wanted"]), {"air"})
        self.assertEqual(out["tiles"][1]["level"], fb.ACT_NOW)

    def test_warm_and_restless(self):
        zones = [zone("A", 1, "MOTION"), zone("B", 2, "MOTION"), zone("C", 3), zone("D", 4)]
        out = fb.describe(classroom("QUIET", comfort="OUT_OF_RANGE", reasons=("too warm",), zones=zones), NODES)
        self.assertIn("Warm and restless", out["tiles"][2]["why"])

    def test_chatter_in_group_work_does_not_alert(self):
        out = fb.describe(classroom("SUSTAINED_CHATTER", mode="DISCUSSION"), NODES)
        self.assertEqual(out["alerts_wanted"], {})

    def test_low_sensor_coverage(self):
        zones = [zone("A", 1), zone("B", 2, status="OFFLINE"), zone("C", 3, status="OFFLINE"),
                 zone("D", 4, status="OFFLINE")]
        out = fb.describe(classroom("QUIET", zones=zones), NODES)
        self.assertIn("coverage", out["alerts_wanted"])
        self.assertEqual(out["sensors"]["level"], fb.ACT_NOW)
        self.assertIn("1 of 4 sensors working", out["sensors"]["text"])


class Alerts(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.alerts = fb.AlertLog(lambda event, fields: self.log.append((event, fields["key"])))

    def test_start_update_end(self):
        self.alerts.update({"air": {"message": "a", "action": "x"}}, 1000)
        self.alerts.update({"air": {"message": "b", "action": "x"}}, 2000)
        view = self.alerts.view(2000)
        self.assertEqual([(a["message"], a["started_ms"]) for a in view["banner"]], [("b", 1000)])
        self.alerts.update({}, 3000)
        view = self.alerts.view(3000)
        self.assertEqual(view["banner"], [])
        self.assertEqual(view["ended"][0]["ended_ms"], 3000)
        self.assertEqual(self.log, [("start", "air"), ("end", "air")])

    def test_vague_update_keeps_the_specific_message(self):
        self.alerts.update({"chatter": {"message": "at back left", "action": "x"}}, 0)
        self.alerts.update({"chatter": {"message": "at some desks", "action": "x", "vague": True}}, 1000)
        self.assertEqual(self.alerts.view(1000)["banner"][0]["message"], "at back left")
        self.assertNotIn("vague", self.alerts.view(1000)["banner"][0])

    def test_hide_for_ten_minutes_then_show_again(self):
        self.alerts.update({"air": {"message": "a", "action": "x"}}, 0)
        alert_id = self.alerts.view(0)["banner"][0]["id"]
        self.assertTrue(self.alerts.hide(alert_id, 1000))
        self.assertFalse(self.alerts.hide(999, 1000))
        self.assertEqual(self.alerts.view(2000)["banner"], [])
        self.assertEqual(self.alerts.view(2000)["hidden"], 1)
        self.assertEqual(len(self.alerts.view(1000 + fb.HIDE_MS)["banner"]), 1)

    def test_a_new_or_worse_alert_shows_while_another_is_hidden(self):
        self.alerts.update({"chatter": {"message": "a", "action": "x"}}, 0)
        self.alerts.hide(self.alerts.view(0)["banner"][0]["id"], 0)
        self.alerts.update({"chatter_air": {"message": "worse", "action": "x"}}, 1000)
        self.assertEqual([a["message"] for a in self.alerts.view(1000)["banner"]], ["worse"])

    def test_sensor_coverage_waits_before_alerting(self):
        wanted = {"coverage": {"message": "m", "action": "a"}}
        self.alerts.update(wanted, 0)
        self.alerts.update(wanted, 14000)
        self.assertEqual(self.alerts.view(14000)["active"], [])
        self.alerts.update({}, 15000)   # Sensors joined: never alerted
        self.alerts.update(wanted, 16000)
        self.alerts.update(wanted, 31000)
        self.assertEqual(len(self.alerts.view(31000)["active"]), 1)


class Api(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(bind=("127.0.0.1", 0), out=io.StringIO(), fusion=FusionEngine())
        self.dashboard = Dashboard(self.server)
        self.httpd = start_http(self.dashboard, "127.0.0.1", 0)
        self.addCleanup(self.server.close)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def request(self, path, data=None):
        try:
            with urllib.request.urlopen(self.base + path, data=data, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_state_has_feedback_and_alerts(self):
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["feedback"]["headline"], "Checking the room…")
        self.assertEqual(state["feedback"]["sensors"]["text"], "No sensors connected yet")
        self.assertEqual(state["alerts"]["banner"], [])
        self.assertNotIn("alerts_wanted", state["feedback"])

    def test_hide_alert(self):
        # /api/state recomputes alerts from the room, so inspect the log directly.
        now = int(time.time() * 1000)
        with self.server.lock:
            self.dashboard.alerts.update({"air": {"message": "m", "action": "a"}}, now)
        alert_id = self.dashboard.alerts.view(now)["banner"][0]["id"]
        self.assertEqual(self.request(f"/api/alerts/{alert_id}/hide", b"{}")[0], 202)
        self.assertEqual(self.request("/api/alerts/999/hide", b"{}")[0], 404)
        view = self.dashboard.alerts.view(int(time.time() * 1000))
        self.assertEqual((view["banner"], view["hidden"]), ([], 1))


def _tokens(css: str, selector: str) -> dict[str, str]:
    block = css[css.index(selector):]
    block = block[block.index("{") + 1:block.index("}")]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _luminance(hex_colour: str) -> float:
    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(hex_colour[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Contrast(unittest.TestCase):
    """WCAG 2.2 AA on the colour pairs the page uses, in both themes."""
    TEXT = [("text", "bg"), ("text", "surface"), ("text", "header"), ("text", "warn-soft"), ("text", "error-soft"),
            ("muted", "bg"), ("muted", "surface"), ("muted", "header"), ("muted", "warn-soft"), ("muted", "error-soft"),
            ("ok-text", "ok-soft"), ("ok-text", "surface"), ("ok-text", "bg"), ("warn-text", "warn-soft"),
            ("warn-text", "surface"), ("error", "error-soft"), ("error", "surface"), ("error", "bg"),
            ("accent-text", "bg"), ("accent-text", "accent-soft"), ("accent-text", "header"),
            ("on-accent", "accent-control"), ("none-text", "bg"), ("none-text", "surface")]
    NON_TEXT = [("control-border", "bg"), ("ok-text", "surface"), ("warn-text", "warn-soft"), ("error", "error-soft")]

    def test_both_themes(self):
        css = (Path(__file__).parents[1] / "mosaic" / "web" / "style.css").read_text()
        for theme, selector in (("light", ":root {"), ("dark", ':root[data-theme="dark"] {')):
            tokens = _tokens(css, selector)
            for pairs, minimum in ((self.TEXT, 4.5), (self.NON_TEXT, 3.0)):
                for fg, bg in pairs:
                    with self.subTest(theme=theme, fg=fg, bg=bg):
                        self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), minimum)

    def test_dark_tokens_match_the_system_dark_block(self):
        css = (Path(__file__).parents[1] / "mosaic" / "web" / "style.css").read_text()
        self.assertEqual(_tokens(css, ':root:not([data-theme="light"]) {'), _tokens(css, ':root[data-theme="dark"] {'))


if __name__ == "__main__":
    unittest.main()
