"""MOSAIC PC gateway: receives node datagrams and tracks each node.

Implements the PC side of docs/protocol.md section 5: packet-loss counting
from seq, reboot detection, ONLINE/STALE/OFFLINE status and PING/PONG
round-trip time. CONFIG delivery is not implemented yet.

Run from the pc/ folder:  python -m mosaic.gateway [--csv telemetry.csv]
Without hardware, run  python -m mosaic.simulator  in a second terminal.

Gateway holds the logic and takes the current time as an argument, so it can
be tested without sockets or sleeping. GatewayServer adds the UDP socket,
console output and the CSV log.
"""

from __future__ import annotations

import argparse
import csv
import enum
import select
import socket
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TextIO

from mosaic import protocol as p

OFFLINE_AFTER_S = 10.0
STALE_AFTER_REPORTS = 3
DEFAULT_REPORT_INTERVAL_MS = 1000
PING_INTERVAL_S = 5.0
SUMMARY_INTERVAL_S = 10.0

_SEQ_MOD = 1 << 32
_NODE_TYPES = (p.MsgType.TELEMETRY, p.MsgType.CONFIG_ACK, p.MsgType.PONG)
Address = tuple[str, int]


class NodeStatus(enum.Enum):
    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


@dataclass
class NodeState:
    node_id: int
    address: Address
    last_seen: float
    last_seq: int
    # Lifetime totals: a reboot restarts seq tracking but keeps these.
    received: int = 0
    lost: int = 0
    duplicates: int = 0
    reboots: int = 0
    telemetry: Optional[p.Telemetry] = None
    last_ack: Optional[p.ConfigAck] = None
    rtt_ms: Optional[float] = None
    # The PC knows this from the CONFIG it sent; default until then.
    report_interval_ms: int = DEFAULT_REPORT_INTERVAL_MS

    @property
    def loss_pct(self) -> float:
        expected = self.received + self.lost
        return 100.0 * self.lost / expected if expected else 0.0

    def status(self, now: float) -> NodeStatus:
        age = now - self.last_seen
        if age > OFFLINE_AFTER_S:
            return NodeStatus.OFFLINE
        if age > STALE_AFTER_REPORTS * self.report_interval_ms / 1000:
            return NodeStatus.STALE
        return NodeStatus.ONLINE


class Gateway:
    """Per-node bookkeeping. `now` is a monotonic time in seconds."""

    def __init__(self) -> None:
        self.nodes: dict[int, NodeState] = {}
        self.dropped: Counter[str] = Counter()  # by source IP
        self.seq = 0  # The PC's own seq for datagrams it sends
        self._reported: dict[int, NodeStatus] = {}

    def handle(self, data: bytes, address: Address,
               now: float) -> Optional[tuple[p.Header, p.Payload]]:
        """Process one received datagram. Returns None if it was dropped."""
        try:
            header, payload = p.decode(data)
        except p.ProtocolError:
            self.dropped[address[0]] += 1
            return None
        if header.msg_type not in _NODE_TYPES or not 1 <= header.node_id <= p.MAX_NODES:
            self.dropped[address[0]] += 1
            return None

        node = self.nodes.get(header.node_id)
        if node is None:
            node = self.nodes[header.node_id] = NodeState(
                header.node_id, address, now, header.seq, received=1)
        else:
            self._track_seq(node, header)
        node.address = address
        node.last_seen = now

        if isinstance(payload, p.Telemetry):
            node.telemetry = payload
        elif isinstance(payload, p.ConfigAck):
            node.last_ack = payload
        else:  # PONG: pc_time_us is our own clock from when the PING left
            node.rtt_ms = (now * 1e6 - payload.pc_time_us) / 1000
        return header, payload

    def _track_seq(self, node: NodeState, header: p.Header) -> None:
        gap = (header.seq - node.last_seq) % _SEQ_MOD
        backwards = gap >= _SEQ_MOD // 2
        # gap == 1 means a PONG/ACK from the new boot already got here first.
        flagged = (header.flags & p.FLAG_FIRST_SINCE_BOOT
                   and header.msg_type == p.MsgType.TELEMETRY and gap != 1)
        if backwards or flagged:
            node.reboots += 1
            node.lost += header.seq  # seq 0 .. seq-1 of the new boot never arrived
        elif gap == 0:
            node.duplicates += 1
        else:
            node.lost += gap - 1
        node.received += 1
        node.last_seq = header.seq

    def pings(self, now: float, port: int = p.PORT_CONFIG) -> list[tuple[bytes, Address]]:
        """One PING per node IP that isn't OFFLINE. Real nodes each have
        their own IP; simulated nodes share one and all answer it."""
        targets = dict.fromkeys(
            node.address[0] for node in self.nodes.values()
            if node.status(now) != NodeStatus.OFFLINE)
        out = []
        for ip in targets:
            header = p.Header(p.MsgType.PING, 0, self.seq, int(now * 1000) % _SEQ_MOD)
            self.seq = (self.seq + 1) % _SEQ_MOD
            out.append((p.encode(header, p.Ping(int(now * 1e6))), (ip, port)))
        return out

    def status_changes(self, now: float) -> list[tuple[int, NodeStatus]]:
        """Nodes whose status changed since the last call."""
        changes = []
        for node_id, node in sorted(self.nodes.items()):
            status = node.status(now)
            if self._reported.get(node_id, NodeStatus.ONLINE) != status:
                changes.append((node_id, status))
            self._reported[node_id] = status
        return changes


def format_telemetry(header: p.Header, t: p.Telemetry) -> str:
    v = t.valid_flags
    parts = [f"node {header.node_id} seq {header.seq:<6}"]
    parts.append(f"{t.temperature_c:5.1f} C {t.humidity_pct:5.1f} %RH"
                 if p.Valid.TEMP_HUM in v else "  -- C    -- %RH")
    if p.Valid.CO2 in v:
        parts.append(f"CO2 {t.co2_ppm:4} ppm")
    else:
        parts.append("CO2 warm-up " if p.Valid.CO2_WARMUP in v else "CO2   --    ")
    parts.append(f"PIR {t.pir_active_pct:3}%" if p.Valid.PIR in v else "PIR  --")
    parts.append(f"{t.audio_class.name} {t.audio_confidence_pct}%"
                 if p.Valid.AUDIO in v else "audio --")
    parts.append(f"RSSI {t.wifi_rssi_dbm} dBm")
    if header.flags & p.FLAG_FIRST_SINCE_BOOT:
        parts.append("(boot)")
    return "  ".join(parts)


def format_summary(gateway: Gateway, now: float) -> str:
    lines = ["node  status   recv   lost  loss%  dup  reboots  rtt_ms"]
    for node_id, n in sorted(gateway.nodes.items()):
        rtt = f"{n.rtt_ms:.1f}" if n.rtt_ms is not None else "--"
        lines.append(f"{node_id:>4}  {n.status(now).value:<7} {n.received:>5} {n.lost:>6} "
                     f"{n.loss_pct:>6.1f} {n.duplicates:>4} {n.reboots:>8}  {rtt:>6}")
    if gateway.dropped:
        drops = ", ".join(f"{ip}: {count}" for ip, count in gateway.dropped.items())
        lines.append(f"dropped datagrams: {drops}")
    return "\n".join(lines)


CSV_FIELDS = [
    "pc_time", "node_id", "seq", "sender_time_ms", "flags",
    "temperature_c", "humidity_pct", "audio_rms", "dsp_time_us", "inference_time_us",
    "free_heap_bytes", "co2_ppm", "config_version", "audio_overruns", "audio_class",
    "pir_active_pct", "audio_prob_pct", "valid_flags", "cpu_load_pct", "wifi_rssi_dbm",
]


def csv_row(header: p.Header, t: p.Telemetry) -> list:
    return [
        datetime.now().isoformat(timespec="milliseconds"), header.node_id, header.seq,
        header.sender_time_ms, header.flags, f"{t.temperature_c:.2f}",
        f"{t.humidity_pct:.2f}", f"{t.audio_rms:.3f}", t.dsp_time_us, t.inference_time_us,
        t.free_heap_bytes, t.co2_ppm, t.config_version, t.audio_overruns, t.audio_class.name,
        t.pir_active_pct, "/".join(map(str, t.audio_prob_pct)), int(t.valid_flags),
        t.cpu_load_pct, t.wifi_rssi_dbm,
    ]


class GatewayServer:
    """The gateway on a UDP socket. Call poll() in a loop, or run()."""

    def __init__(self, bind: Address = ("0.0.0.0", p.PORT_TELEMETRY),
                 config_port: int = p.PORT_CONFIG, ping_interval: float = PING_INTERVAL_S,
                 summary_interval: float = SUMMARY_INTERVAL_S,
                 csv_file: Optional[TextIO] = None, out: TextIO = sys.stdout) -> None:
        self.gateway = Gateway()
        self.config_port = config_port
        self.ping_interval = ping_interval
        self.summary_interval = summary_interval
        self.out = out
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(bind)
        self.csv = csv.writer(csv_file) if csv_file else None
        self._csv_file = csv_file
        if self.csv and csv_file.tell() == 0:
            self.csv.writerow(CSV_FIELDS)
        now = time.monotonic()
        self._next_ping = now + ping_interval
        self._next_summary = now + summary_interval

    def poll(self, timeout: float = 0.2) -> None:
        readable, _, _ = select.select([self.sock], [], [], timeout)
        if readable:
            try:
                data, address = self.sock.recvfrom(p.MAX_DATAGRAM + 1)
            except ConnectionResetError:
                # Windows reports an ICMP "port unreachable" for an earlier
                # PING here (WSAECONNRESET). Harmless: the node is offline.
                data = None
            if data is not None:
                self._received(data, address, time.monotonic())
        now = time.monotonic()
        for node_id, status in self.gateway.status_changes(now):
            self._print(f"node {node_id} is now {status.value}")
        if now >= self._next_ping:
            self.send_pings()
            self._next_ping = now + self.ping_interval
        if now >= self._next_summary:
            self._print(format_summary(self.gateway, now))
            self._next_summary = now + self.summary_interval

    def _received(self, data: bytes, address: Address, now: float) -> None:
        result = self.gateway.handle(data, address, now)
        if result is None:
            return
        header, payload = result
        if isinstance(payload, p.Telemetry):
            self._print(format_telemetry(header, payload))
            if self.csv:
                self.csv.writerow(csv_row(header, payload))
                self._csv_file.flush()
        elif isinstance(payload, p.ConfigAck):
            self._print(f"node {header.node_id} CONFIG_ACK version "
                        f"{payload.config_version}: {payload.status.name}")

    def send_pings(self) -> None:
        for data, address in self.gateway.pings(time.monotonic(), self.config_port):
            try:
                self.sock.sendto(data, address)
            except OSError as e:  # e.g. network unreachable; try again next round
                self._print(f"PING to {address[0]} failed: {e}")

    def run(self) -> None:
        host, port = self.sock.getsockname()
        self._print(f"MOSAIC gateway listening on UDP {host}:{port} (Ctrl+C to stop)")
        try:
            while True:
                self.poll()
        except KeyboardInterrupt:
            self._print("\n" + format_summary(self.gateway, time.monotonic()))

    def close(self) -> None:
        self.sock.close()

    def _print(self, text: str) -> None:
        print(text, file=self.out, flush=True)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="MOSAIC PC gateway (protocol v1)")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on")
    parser.add_argument("--port", type=int, default=p.PORT_TELEMETRY)
    parser.add_argument("--node-port", type=int, default=p.PORT_CONFIG,
                        help="port nodes listen on for PING/CONFIG")
    parser.add_argument("--ping-interval", type=float, default=PING_INTERVAL_S)
    parser.add_argument("--csv", metavar="FILE", help="append every TELEMETRY to this CSV")
    args = parser.parse_args(argv)

    csv_file = open(args.csv, "a", newline="") if args.csv else None
    server = GatewayServer((args.host, args.port), args.node_port, args.ping_interval,
                           csv_file=csv_file)
    try:
        server.run()
    finally:
        server.close()
        if csv_file:
            csv_file.close()


if __name__ == "__main__":
    main()
