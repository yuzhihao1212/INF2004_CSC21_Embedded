"""MOSAIC dashboard: the gateway plus a live web page.

Run from the pc/ folder, then open http://localhost:8050 :
    python -m mosaic.dashboard
    python -m mosaic.dashboard --simulate 3     # rehearse without hardware

The page (mosaic/web/) polls /api/state once a second. The CO2 bands are
display thresholds only; sensor fusion (occupancy, alerts) is not built yet.
Standard library only, like the gateway.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from mosaic import protocol as p
from mosaic import simulator
from mosaic.gateway import PING_INTERVAL_S, GatewayServer, NodeState

HTTP_PORT = 8050
HISTORY_S = 600
CO2_FAIR_PPM = 800   # Common classroom guidance; tune with the fusion thresholds
CO2_POOR_PPM = 1200
WEB_DIR = Path(__file__).with_name("web")
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
    if p.Valid.AUDIO in v:
        audio = {"class": t.audio_class.name.lower(), "confidence": t.audio_confidence_pct,
                 "probs": list(t.audio_prob_pct)}
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
    parser.add_argument("--verbose", action="store_true", help="print every packet")
    args = parser.parse_args(argv)

    csv_file = open(args.csv, "a", newline="") if args.csv else None
    quiet = None if args.verbose else open(os.devnull, "w")
    server = GatewayServer((args.host, args.port), args.node_port, args.ping_interval,
                           csv_file=csv_file, out=quiet or sys.stdout)
    dashboard = Dashboard(server)
    httpd = start_http(dashboard, args.http_host, args.http_port)
    url_host = "localhost" if args.http_host in ("127.0.0.1", "0.0.0.0") else args.http_host
    print(f"MOSAIC dashboard: http://{url_host}:{httpd.server_address[1]}  "
          f"(nodes send to UDP {args.port}; Ctrl+C to stop)", flush=True)

    if args.simulate:
        sim_args = ["--nodes", str(args.simulate), "--pc-ip", "127.0.0.1",
                    "--pc-port", str(args.port), "--listen-port", str(args.node_port)]
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
