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
fusion engine's classroom states under "classroom". The CO2 bands are
display colours only; fusion has its own thresholds.
Standard library only, like the gateway.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
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
from mosaic import simulator
from mosaic.fusion import FusionEngine
from mosaic.gateway import (PING_INTERVAL_S, ConfigDelivery, GatewayServer, NodeState,
                            add_fusion_argument, load_fusion_config)

HTTP_PORT = 8050
HISTORY_S = 600
CO2_FAIR_PPM = 800   # Common classroom guidance; tune with the fusion thresholds
CO2_POOR_PPM = 1200
WEB_DIR = Path(__file__).with_name("web")
_CONFIG_PATH = re.compile(r"/api/nodes/(\d+)/config")
_MAX_BODY = 4096
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                  ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Dashboard:
    """Keeps a short history per node and builds the JSON the page shows."""

    def __init__(self, server: GatewayServer, history_s: float = HISTORY_S) -> None:
        self.server = server
        self.history_s = history_s
        # node_id -> [wall_ms, temp_c, humidity_pct, co2_ppm, pir_pct]; None = invalid
        self.history: dict[int, deque[list]] = {}
        server.telemetry_listeners.append(self._record)

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
            if self.server.fusion:
                self.server.fusion.evaluate(
                    now, {n.node_id for n in gateway.nodes.values()
                          if n.status(now).value == "ONLINE"},
                    {n.node_id for n in gateway.nodes.values() if n.status(now).value == "STALE"})
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
                "classroom": self.server.fusion.state() if self.server.fusion else None,
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
                 "probs": list(w.prob_pct)}
    return {
        "temperature_c": round(t.temperature_c, 1) if p.Valid.TEMP_HUM in v else None,
        "humidity_pct": round(t.humidity_pct, 1) if p.Valid.TEMP_HUM in v else None,
        "co2_ppm": t.co2_ppm if p.Valid.CO2 in v else None,
        "co2_warmup": p.Valid.CO2_WARMUP in v,
        "pir_pct": t.pir_active_pct if p.Valid.PIR in v else None,
        "audio": audio,
        "rssi_dbm": t.wifi_rssi_dbm,
        "config_version": t.config_version,
    }


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
            if path in ("/api/calibrate", "/api/calibrate/reset"):
                return self._post_calibrate(reset=path.endswith("/reset"))
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
                    if reset:
                        fusion.reset_reference(body.get("zone"))
                    else:
                        fusion.calibrate(time.monotonic(), body.get("zone"))
                except KeyError:
                    return self._json(404, {"error": "unknown student zone"})
                self._json(202, {"reference": fusion.reference.state()})

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
    add_fusion_argument(parser)
    args = parser.parse_args(argv)
    if args.scenario and not args.simulate:
        args.simulate = 4  # Scenarios script zones A-D
    fusion = FusionEngine(load_fusion_config(parser, args.fusion_config))

    csv_file = open(args.csv, "a", newline="") if args.csv else None
    quiet = None if args.verbose else open(os.devnull, "w")
    server = GatewayServer((args.host, args.port), args.node_port, args.ping_interval,
                           csv_file=csv_file, out=quiet or sys.stdout, fusion=fusion,
                           fusion_out=sys.stdout)
    dashboard = Dashboard(server)
    httpd = start_http(dashboard, args.http_host, args.http_port)
    url_host = "localhost" if args.http_host in ("127.0.0.1", "0.0.0.0") else args.http_host
    print(f"MOSAIC dashboard: http://{url_host}:{httpd.server_address[1]}  "
          f"(nodes send to UDP {args.port}; Ctrl+C to stop)", flush=True)

    if args.simulate:
        sim_args = ["--nodes", str(args.simulate), "--pc-ip", "127.0.0.1",
                    "--pc-port", str(args.port), "--listen-port", str(args.node_port)]
        if args.scenario:
            sim_args += ["--scenario", args.scenario]
        if args.aligned:
            sim_args += ["--aligned"]
        sim_args += ["--receive-jitter-ms", str(args.receive_jitter_ms)]
        threading.Thread(target=simulator.main, args=(sim_args,), daemon=True).start()

    try:
        server.run()
    finally:
        httpd.shutdown()
        server.close()
        for f in (csv_file, quiet):
            if f:
                f.close()


if __name__ == "__main__":
    main()
