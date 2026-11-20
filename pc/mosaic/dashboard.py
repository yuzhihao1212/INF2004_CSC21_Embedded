"""MOSAIC dashboard: the gateway plus a live web page.

Run from the pc/ folder, then open http://localhost:8050 :
    python -m mosaic.dashboard
    python -m mosaic.dashboard --simulate 3     # rehearse without hardware
    python -m mosaic.dashboard --scenario demo  # 4 simulated nodes play a scripted classroom

The page (mosaic/web/) polls /api/state once a second. To change a node's
settings, POST the fields to change as JSON to /api/nodes/<id>/config, e.g.
    curl -d '{"report_interval_ms": 500, "mode": "DISCUSSION"}' \
         http://localhost:8050/api/nodes/1/config
The gateway then delivers it as a CONFIG and /api/state shows its progress.
POST {"mode": "DISCUSSION"} to /api/mode to change the classroom mode: fusion
switches rules and every node gets the new mode. /api/state includes the
fusion engine's classroom states under "classroom", and their plain-language
description, severity and alerts under "feedback" and "alerts" (feedback.py).
With --simulate, "simulation" names the scenario and the phase being played.
POST {"pause": true|false}, {"next": true} or {"rate": 1|2|4} to /api/simulation
to pause, skip or speed up a --scenario script (the page's Space, right arrow
and 1/2/4 keys). Only the script moves; nodes keep their real report timing.
POST to /api/alerts/<id>/hide to keep an alert off the banner for 10 minutes.
Excessive noise: hold a steady sound at the target level next to a student
area's sensor and POST {"zone": "B"} to /api/loudness/capture; that sensor's
mean level over the next 5 s becomes the area's loud level. POST the same to
/api/loudness/clear to remove it. --loud-levels FILE keeps them across restarts.
The CO2 bands are display colours only; fusion has its own thresholds.
Standard library only, like the gateway.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from mosaic import protocol as p
from mosaic import scenarios, simulator
from mosaic.feedback import AlertLog, describe
from mosaic.fusion import FusionEngine
from mosaic.gateway import (PING_INTERVAL_S, ConfigDelivery, GatewayServer, NodeState,
                            add_fusion_argument, add_mqtt_argument, load_fusion_config,
                            make_transport)

HTTP_PORT = 8050
HISTORY_S = 600
CO2_FAIR_PPM = 800   # Common classroom guidance; tune with the fusion thresholds
CO2_POOR_PPM = 1200
WEB_DIR = Path(__file__).with_name("web")
_CONFIG_PATH = re.compile(r"/api/nodes/(\d+)/config")
_HIDE_PATH = re.compile(r"/api/alerts/(\d+)/hide")
_MAX_BODY = 4096
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                  ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                  ".woff2": "font/woff2"}  # Self-hosted font: the demo hotspot has no internet


class Dashboard:
    """Keeps a short history per node and builds the JSON the page shows."""

    def __init__(self, server: GatewayServer, history_s: float = HISTORY_S,
                 loud_levels_path: Optional[Path] = None) -> None:
        self.server = server
        self.loud_levels_path = loud_levels_path
        self._saved_loud: dict[str, int] = {}
        if loud_levels_path and server.fusion:
            self._saved_loud = load_loud_levels(loud_levels_path, server.fusion)
        self.history_s = history_s
        # node_id -> [wall_ms, temp_c, humidity_pct, co2_ppm, pir_pct]; None = invalid
        self.history: dict[int, deque[list]] = {}
        self.alerts = AlertLog(self._log_alert)
        self._next_tick = 0.0
        self._simulation: Optional[tuple[int, Optional[str], Optional[scenarios.ScriptClock]]] = None
        server.telemetry_listeners.append(self._record)
        server.tick_listeners.append(self._tick)

    def simulating(self, nodes: int, scenario: Optional[str],
                   clock: Optional[scenarios.ScriptClock] = None) -> None:
        """Record the in-process simulator run and the script clock it shares."""
        self._simulation = (nodes, scenario, clock)

    def control_simulation(self, body: object, now: float) -> dict:
        """Pause, skip or change the speed of the scenario script. Raises
        LookupError when no script is running, ValueError on a bad body."""
        clock = self._simulation[2] if self._simulation else None
        if clock is None:
            raise LookupError("no scenario script is running")
        if not isinstance(body, dict) or len(body) != 1 or not set(body) <= {"pause", "next", "rate", "ventilation"}:
            raise ValueError('expected {"pause": true|false}, {"next": true}, {"rate": 1|2|4} '
                             'or {"ventilation": true|false}')
        (action, value), = body.items()
        if action == "pause":
            if not isinstance(value, bool):
                raise ValueError('"pause" must be true or false')
            clock.set_paused(now, value)
        elif action == "rate":
            if isinstance(value, bool) or value not in clock.RATES:
                raise ValueError(f'"rate" must be one of {list(clock.RATES)}')
            clock.set_rate(now, value)
        elif action == "ventilation":
            if not isinstance(value, bool):
                raise ValueError('"ventilation" must be true or false')
            clock.set_ventilation(value)
        elif value is not True:
            raise ValueError('"next" must be true')
        elif not clock.next_phase(now):
            raise ValueError("already on the last phase")
        index, phase = clock.phase(now)
        # Logged so an evaluation run that was skipped or sped up can be told apart
        self.server._log("simulation", now, action=action, value=value,
                         phase=index + 1, label=phase.label, rate=clock.rate, paused=clock.paused,
                         ventilation=clock.ventilation)
        return self.simulation(now)

    def simulation(self, now: float) -> Optional[dict]:
        """Scenario and phase being played, or None when no simulator runs here.

        The phase comes from the script clock the simulator thread shares, so
        it matches what the nodes are playing, including pauses, skips and speed.
        """
        if self._simulation is None:
            return None
        nodes, name, clock = self._simulation
        scenario = scenarios.get(name)
        if scenario is None or clock is None:
            return {"nodes": nodes, "scenario": None}
        elapsed = clock.elapsed(now)
        index, phase = scenario.phase_at(elapsed)
        phase_end = sum(ph.seconds for ph in scenario.phases[:index + 1])
        return {
            "nodes": nodes,
            "scenario": name,
            "description": scenario.description,
            "phases": [{"label": ph.label, "seconds": ph.seconds} for ph in scenario.phases],
            "phase": index,
            "label": phase.label,
            "expect": phase.expect,
            "elapsed_s": round(elapsed, 1),
            "left_s": round(max(0.0, phase_end - elapsed), 1),
            "finished": elapsed >= scenario.seconds,
            "paused": clock.paused,
            "rate": clock.rate,
            "ventilation": clock.ventilation,
        }

    def _log_alert(self, action: str, fields: dict) -> None:
        self.server._log("alert", time.monotonic(), action=action, **fields)

    def _tick(self, now: float) -> None:
        """Keep alerts current once a second even when no page is open."""
        if self.server.fusion and now >= self._next_tick:
            self._next_tick = now + 1.0
            self._feedback([self._node(n, now) for _, n in sorted(self.server.gateway.nodes.items())])

    def _feedback(self, nodes: list[dict]) -> tuple[dict, dict]:
        """Classroom, its plain-language description; updates alerts. Lock held."""
        fusion = self.server.fusion
        classroom = present_classroom(fusion)
        wall_ms = int(time.time() * 1000)
        now_ms = classroom["now_ms"]
        events = [{"wall_ms": wall_ms - (now_ms - e.time_ms), "region": e.region, "old": e.old,
                   "new": e.new} for e in fusion.events if e.region in ("activity", "air", "comfort", "mode")]
        feedback = describe(classroom, nodes, events, wall_ms)
        self.alerts.update(feedback.pop("alerts_wanted"), wall_ms)
        self._save_loud_levels()
        return classroom, feedback

    def _save_loud_levels(self) -> None:
        """Write the loud levels when a capture or clear changed them. Lock held."""
        levels = self.server.fusion.config.loud_levels_x16
        if levels == self._saved_loud:
            return
        for zone in sorted(set(levels) | set(self._saved_loud)):
            if levels.get(zone) != self._saved_loud.get(zone):
                self.server._log("loudness", time.monotonic(), zone=zone, action="set",
                                 level_x16=levels.get(zone))
        self._saved_loud = dict(levels)
        if self.loud_levels_path:
            try:
                self.loud_levels_path.write_text(json.dumps({"version": 1, "levels_x16": levels}, indent=2) + "\n")
            except OSError as e:
                print(f"Could not save loud levels to {self.loud_levels_path}: {e}", file=sys.stderr)

    def _record(self, header: p.Header, t: p.Telemetry, now: float) -> None:
        v = t.valid_flags
        wall_ms = int(time.time() * 1000)
        point = [
            wall_ms,
            round(t.temperature_c, 1) if p.Valid.TEMP_HUM in v else None,
            round(t.humidity_pct, 1) if p.Valid.TEMP_HUM in v else None,
            t.co2_ppm if p.Valid.CO2 in v else None,
            t.pir_active_pct if p.Valid.PIR in v else None,
        ]
        points = self.history.setdefault(header.node_id, deque())
        points.append(point)
        while points and points[0][0] < wall_ms - self.history_s * 1000:
            points.popleft()

    def state(self) -> dict:
        with self.server.lock:
            now = time.monotonic()
            gateway = self.server.gateway
            nodes = [self._node(n, now) for _, n in sorted(gateway.nodes.items())]
            classroom = feedback = None
            if self.server.fusion:
                self.server._evaluate_fusion(now)
                classroom, feedback = self._feedback(nodes)
            simulated = {n["simulated"] for n in nodes}
            return {
                "time_ms": int(time.time() * 1000),
                "history_s": self.history_s,
                "co2_bands": {"fair": CO2_FAIR_PPM, "poor": CO2_POOR_PPM},
                "dropped": sum(gateway.dropped.values()),
                # none / simulated / sensors / mixed, for the header indicator
                "source": ("none" if not nodes else "mixed" if len(simulated) == 2
                           else "simulated" if True in simulated else "sensors"),
                "nodes": nodes,
                "classroom": classroom,
                "feedback": feedback,
                "alerts": self.alerts.view(int(time.time() * 1000)),
                "simulation": self.simulation(now),
            }

    def _node(self, n: NodeState, now: float) -> dict:
        return {
            "id": n.node_id,
            "status": n.status(now).value.lower(),
            "age_s": round(now - n.last_seen, 1),
            "ip": n.address[0],
            "simulated": is_simulated(n.address[0]),
            "received": n.received,
            "lost": n.lost,
            "gaps_detected": n.gaps_detected,
            "recovered": n.recovered,
            "duplicates": n.duplicates,
            "loss_pct": round(n.loss_pct, 1),
            "reboots": n.reboots,
            "rtt_ms": None if n.rtt_ms is None else round(n.rtt_ms, 1),
            "telemetry": _telemetry(n.telemetry) if n.telemetry else None,
            "config": _config(n.config) if n.config else None,
            "history": list(self.history.get(n.node_id, ())),
        }


def is_simulated(ip: str) -> bool:
    """Packets from this computer come from the simulator; a real Pico always
    sends from its own Wi-Fi address. The protocol itself has no such flag, so
    a simulator run on another computer would show as real."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def _telemetry(t: p.Telemetry) -> dict:
    v = t.valid_flags
    audio = None
    if t.latest_audio:
        w = t.latest_audio
        audio = {"class": w.audio_class.name.lower(), "confidence": w.confidence_pct,
                 "probs": list(w.prob_pct), "rms": w.rms_x16 / 16}  # AC RMS, ADC counts
    return {
        "temperature_c": round(t.temperature_c, 1) if p.Valid.TEMP_HUM in v else None,
        "humidity_pct": round(t.humidity_pct, 1) if p.Valid.TEMP_HUM in v else None,
        "co2_ppm": t.co2_ppm if p.Valid.CO2 in v else None,
        "co2_warmup": p.Valid.CO2_WARMUP in v,
        "pir_pct": t.pir_active_pct if p.Valid.PIR in v else None,
        "audio": audio,
        "rssi_dbm": t.wifi_rssi_dbm,
        "config_version": t.config_version,
        # Node vitals for the Sensors page's health cards (S4 node health, S1/S2 timing)
        "cpu_load_pct": t.cpu_load_pct,
        "free_heap_bytes": t.free_heap_bytes,
        "audio_overruns": t.audio_overruns,
        "dsp_time_us": t.dsp_time_us,
        "inference_time_us": t.inference_time_us,
    }


def present_reference(reference: dict, fusion: FusionEngine) -> dict:
    """Presentation only: integer fusion quantities -> human decimal ADC units.

    isqrt rounds display RMS down to Q12.4; the displayed threshold is also
    rounded down to Q12.4. These values NEVER feed back into a decision.
    Raw integer fields remain in the JSON for numeric evidence and clients.
    """
    cfg = fusion.reference.config
    for status in reference["zones"].values():
        for raw, shown, scale in (("gain_q16", "gain", 65536),
                                  ("background_power_x256", "background_power", 256),
                                  ("upper_residual_x256", "upper_residual", 256),
                                  ("student_rms_x16", "student_rms", 16),
                                  ("talking_pct", "talking_fraction", 100)):
            value = status.get(raw)
            status[shown] = value / scale if value is not None else None
        expected = status["expected_power_x256"]
        power = status["threshold_power_x256"]
        status["expected_rms"] = math.isqrt(expected) / 16 if expected is not None else None
        status["threshold"] = ((math.isqrt(power * (100 + cfg.relative_margin_pct) ** 2) // 100
                                + cfg.abs_margin_x16) / 16 if power is not None else None)
    return reference


def load_loud_levels(path: Path, fusion: FusionEngine) -> dict[str, int]:
    """Merge saved loud levels into fusion. A missing file is fine; levels for
    zones that are no longer student zones are dropped."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("levels_x16"), dict):
        raise ValueError(f"{path}: expected {{\"version\": 1, \"levels_x16\": {{...}}}}")
    cfg = fusion.config
    students = set(cfg.zones.values()) - {cfg.reference_zone}
    for zone, level in data["levels_x16"].items():
        if zone in students and type(level) is int and 1 <= level <= 65535:
            cfg.loud_levels_x16[zone] = level
    return dict(cfg.loud_levels_x16)


def present_classroom(fusion: FusionEngine) -> dict:
    """Decimals belong to this display boundary, never fusion/reference.py."""
    result = fusion.state()
    result["confidence"] = result["confidence_pct"] / 100
    result["air_recovered_ppm"] = fusion.config.co2_recovered_ppm  # For the page's "Clearing" wording
    present_reference(result["reference"], fusion)
    for zone in result["zones"]:
        for raw, shown in (("temperature_x10", "temperature_c"), ("humidity_x10", "humidity_pct")):
            zone[shown] = zone[raw] / 10 if zone[raw] is not None else None
    return result


def _config(d: ConfigDelivery) -> dict:
    c = d.config
    return {
        "version": c.config_version,
        "state": d.state.value.lower(),
        "sends": d.sends,
        "ack": d.status.name if d.status is not None else None,
        "report_interval_ms": c.report_interval_ms,
        "dht_interval_ms": c.dht_interval_ms,
        "co2_interval_ms": c.co2_interval_ms,
        "audio_gain_x256": c.audio_gain_x256,
        "mode": c.mode.name,
        "audio_conf_threshold_pct": c.audio_conf_threshold_pct,
    }


def config_fields(body: dict) -> dict:
    """Validate a JSON config request into Config field values. `mode` may be
    a name ("DISCUSSION") or a number. Raises ValueError."""
    if not isinstance(body, dict) or not body:
        raise ValueError("expected a JSON object of fields to change")
    fields = {}
    for name, value in body.items():
        if name == "mode" and isinstance(value, str):
            try:
                value = p.Mode[value.upper()]
            except KeyError:
                raise ValueError(f"unknown mode {value!r}") from None
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        fields[name] = value
    return fields


def make_handler(dashboard: Dashboard) -> type[BaseHTTPRequestHandler]:
    web_root = WEB_DIR.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                body = json.dumps(dashboard.state(), separators=(",", ":")).encode()
                return self._send(200, "application/json", body)
            # Only files directly inside web/: no path traversal.
            file = (web_root / (path.lstrip("/") or "index.html")).resolve()
            if file.parent != web_root or not file.is_file() or file.suffix not in _CONTENT_TYPES:
                return self._send(404, "text/plain; charset=utf-8", b"Not found")
            self._send(200, _CONTENT_TYPES[file.suffix], file.read_bytes())

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/mode":
                return self._post_mode()
            if path == "/api/simulation":
                return self._post_simulation()
            if path in ("/api/calibrate", "/api/calibrate/reset"):
                return self._post_calibrate(reset=path.endswith("/reset"))
            if path in ("/api/loudness/capture", "/api/loudness/clear"):
                return self._post_loudness(clear=path.endswith("/clear"))
            hide = _HIDE_PATH.fullmatch(path)
            if hide:
                with dashboard.server.lock:
                    found = dashboard.alerts.hide(int(hide[1]), int(time.time() * 1000))
                return self._json(202 if found else 404, {"hidden": found})
            match = _CONFIG_PATH.fullmatch(path)
            if not match:
                return self._send(404, "text/plain; charset=utf-8", b"Not found")
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                fields = config_fields(json.loads(self.rfile.read(length) or b"null"))
                config = dashboard.server.set_config(int(match[1]), **fields)
            except KeyError:
                return self._json(404, {"error": f"node {match[1]} has not reported yet"})
            except ValueError as e:  # Includes malformed JSON
                return self._json(400, {"error": str(e)})
            self._json(202, {"config_version": config.config_version})

        def _post_simulation(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"null")
                with dashboard.server.lock:
                    reply = dashboard.control_simulation(body, time.monotonic())
            except LookupError as e:
                return self._json(409, {"error": str(e)})
            except ValueError as e:  # Includes malformed JSON
                return self._json(400, {"error": str(e)})
            self._json(200, reply)

        def _post_mode(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"null")
                if not isinstance(body, dict) or set(body) != {"mode"}:
                    raise ValueError('expected {"mode": "LECTURE" | "DISCUSSION" | "QUIET_WORK"}')
                mode = p.Mode(config_fields(body)["mode"])
                nodes = dashboard.server.set_mode(mode)
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            self._json(202, {"mode": mode.name, "nodes": nodes})

        def _post_calibrate(self, *, reset: bool) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > _MAX_BODY:
                    return self._json(413, {"error": "request too large"})
                if length < 0:
                    raise ValueError("invalid request length")
                body = json.loads(self.rfile.read(length) or b"{}")
                if (not isinstance(body, dict) or set(body) - {"zone"}
                        or ("zone" in body and not isinstance(body["zone"], str))):
                    raise ValueError('expected {} or {"zone": "student zone"}')
            except (ValueError, UnicodeError) as e:
                return self._json(400, {"error": str(e)})
            with dashboard.server.lock:
                fusion = dashboard.server.fusion
                if fusion is None or not fusion.reference.enabled:
                    return self._json(409, {"error": "reference comparison is disabled or unmapped"})
                try:
                    now = time.monotonic()
                    if reset:
                        fusion.reset_reference(body.get("zone"))
                    else:
                        fusion.calibrate(now, body.get("zone"))
                    dashboard.server.reference_operation("reset" if reset else "start", body.get("zone"), now)
                except KeyError:
                    return self._json(404, {"error": "unknown student zone"})
                self._json(202, {"reference": present_reference(fusion.reference.state(), fusion)})

        def _post_loudness(self, *, clear: bool) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > _MAX_BODY:
                    return self._json(413, {"error": "request too large"})
                if length < 0:
                    raise ValueError("invalid request length")
                body = json.loads(self.rfile.read(length) or b"null")
                if not isinstance(body, dict) or set(body) != {"zone"} or not isinstance(body["zone"], str):
                    raise ValueError('expected {"zone": "student zone"}')
            except (ValueError, UnicodeError) as e:
                return self._json(400, {"error": str(e)})
            with dashboard.server.lock:
                fusion = dashboard.server.fusion
                if fusion is None:
                    return self._json(409, {"error": "fusion is not running"})
                try:
                    if clear:
                        fusion.clear_loud(body["zone"])
                    else:
                        fusion.capture_loud(time.monotonic(), body["zone"])
                except KeyError:
                    return self._json(404, {"error": "unknown student zone"})
                dashboard.server._log("loudness", time.monotonic(), zone=body["zone"],
                                      action="clear" if clear else "capture")
                dashboard._save_loud_levels()
                self._json(202, {"zone": body["zone"], "action": "clear" if clear else "capture"})

        def _json(self, code: int, value: dict) -> None:
            self._send(code, "application/json", json.dumps(value).encode())

        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # Keep the console for the gateway
            pass

    return Handler


def start_http(dashboard: Dashboard, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(dashboard))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="MOSAIC gateway with live dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="UDP address to listen on for nodes")
    parser.add_argument("--port", type=int, default=p.PORT_TELEMETRY)
    parser.add_argument("--node-port", type=int, default=p.PORT_CONFIG)
    parser.add_argument("--ping-interval", type=float, default=PING_INTERVAL_S)
    parser.add_argument("--http-host", default="127.0.0.1",
                        help="0.0.0.0 to open the dashboard to other devices")
    parser.add_argument("--http-port", type=int, default=HTTP_PORT)
    parser.add_argument("--csv", metavar="FILE", help="append every TELEMETRY to this CSV")
    parser.add_argument("--simulate", type=int, default=0, metavar="N",
                        help="also run N simulated nodes in this process")
    simulator.add_scenario_argument(parser)
    simulator.add_timing_arguments(parser)
    parser.add_argument("--verbose", action="store_true", help="print every packet")
    parser.add_argument("--events", metavar="FILE", help="append JSON Lines evaluation events")
    add_mqtt_argument(parser)
    add_fusion_argument(parser)
    parser.add_argument("--loud-levels", metavar="FILE",
                        help="load and save each area's excessive-noise level (JSON)")
    args = parser.parse_args(argv)
    if args.scenario and not args.simulate:
        args.simulate = 4  # Scenarios script zones A-D
    transport = make_transport(parser, args.mqtt)
    fusion = FusionEngine(load_fusion_config(parser, args.fusion_config))

    csv_file = open(args.csv, "a", newline="") if args.csv else None
    events_file = open(args.events, "a") if args.events else None
    quiet = None if args.verbose else open(os.devnull, "w")
    server = GatewayServer((args.host, args.port), args.node_port, args.ping_interval,
                           csv_file=csv_file, out=quiet or sys.stdout, fusion=fusion,
                           fusion_out=sys.stdout, events_file=events_file, transport=transport)
    try:
        dashboard = Dashboard(server, loud_levels_path=Path(args.loud_levels) if args.loud_levels else None)
    except (OSError, ValueError) as e:
        server.close()
        parser.error(f"--loud-levels: {e}")
    if args.scenario and not fusion.config.loud_levels_x16:
        # No sound meter in a simulation: use the scenario's stand-in levels.
        fusion.config.loud_levels_x16.update(
            scenarios.sim_loud_levels(fusion.config.zones, fusion.config.reference_zone))
        dashboard._saved_loud = dict(fusion.config.loud_levels_x16)
    httpd = start_http(dashboard, args.http_host, args.http_port)
    url_host = "localhost" if args.http_host in ("127.0.0.1", "0.0.0.0") else args.http_host
    print(f"MOSAIC dashboard: http://{url_host}:{httpd.server_address[1]}  "
          f"(nodes reach it on {server.transport.describe()}; Ctrl+C to stop)", flush=True)

    if args.simulate:
        sim_args = ["--nodes", str(args.simulate), "--pc-ip", "127.0.0.1",
                    "--pc-port", str(args.port), "--listen-port", str(args.node_port)]
        if args.mqtt:
            sim_args += ["--mqtt", args.mqtt]
        if args.scenario:
            sim_args += ["--scenario", args.scenario]
        if args.aligned:
            sim_args += ["--aligned"]
        sim_args += ["--receive-jitter-ms", str(args.receive_jitter_ms)]
        scenario = scenarios.get(args.scenario)
        clock = scenarios.ScriptClock(scenario) if scenario else None
        if clock:
            clock.start(time.monotonic())
        dashboard.simulating(args.simulate, args.scenario, clock)
        threading.Thread(target=simulator.main, args=(sim_args, clock), daemon=True).start()

    try:
        server.run()
    finally:
        httpd.shutdown()
        server.close()
        for f in (csv_file, events_file, quiet):
            if f:
                f.close()


if __name__ == "__main__":
    main()
