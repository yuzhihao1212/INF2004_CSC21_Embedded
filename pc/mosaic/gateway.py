"""MOSAIC PC gateway: receives node datagrams and tracks each node.

Implements the PC side of docs/protocol.md section 5: packet-loss counting
from seq, reboot detection, ONLINE/STALE/OFFLINE status, PING/PONG
round-trip time and CONFIG delivery (retries, self-healing after a node
reboots, and recovery from STALE_VERSION).

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
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, TextIO

from mosaic import protocol as p
from mosaic.fusion import FusionConfig, FusionEngine, format_event

OFFLINE_AFTER_S = 10.0
STALE_AFTER_REPORTS = 3
DEFAULT_REPORT_INTERVAL_MS = 1000
PING_INTERVAL_S = 5.0
SUMMARY_INTERVAL_S = 10.0
CONFIG_RETRY_S = 0.5
CONFIG_MAX_SENDS = 5
CONFIG_FAILED_WAIT_S = 10.0  # After 5 unanswered sends, before self-healing tries again

_SEQ_MOD = 1 << 32
_NODE_TYPES = (p.MsgType.TELEMETRY, p.MsgType.CONFIG_ACK, p.MsgType.PONG)
Address = tuple[str, int]


class NodeStatus(enum.Enum):
    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


class ConfigState(enum.Enum):
    SENDING = "SENDING"    # Waiting for a CONFIG_ACK; resent every CONFIG_RETRY_S
    APPLIED = "APPLIED"    # Node acknowledged it, or reports this config_version
    FAILED = "FAILED"      # CONFIG_MAX_SENDS sends without an answer
    REJECTED = "REJECTED"  # Node answered INVALID_VALUE or UNSUPPORTED


@dataclass
class ConfigDelivery:
    """The configuration the PC wants a node to run, and how delivery is going."""
    config: p.Config
    state: ConfigState = ConfigState.SENDING
    sends: int = 0
    next_send: float = 0.0
    # seq of the node's datagram that confirmed it. TELEMETRY sent before
    # that may still show the old version and must not trigger a resend.
    confirmed_seq: Optional[int] = None
    status: Optional[p.AckStatus] = None  # Last ACK status for this config


def _seq_after(a: int, b: int) -> bool:
    """True if seq a was sent after seq b, allowing for wrap-around."""
    return 0 < (a - b) % _SEQ_MOD < _SEQ_MOD // 2


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
    config: Optional[ConfigDelivery] = None

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
        self.messages: list[str] = []  # Config events for the console; caller drains it

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
            self._check_config(node, header, payload, now)
        elif isinstance(payload, p.ConfigAck):
            node.last_ack = payload
            self._config_acked(node, header, payload, now)
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
            if node.config:  # The confirmation was from before the reboot
                node.config.confirmed_seq = None
        elif gap == 0:
            node.duplicates += 1
        else:
            node.lost += gap - 1
        node.received += 1
        node.last_seq = header.seq

    def pings(self, now: float, port: int = p.PORT_CONFIG) -> list[tuple[bytes, Address]]:
        """One PING per node that isn't OFFLINE, addressed by node_id. A node
        ignores PC messages for another ID, so simulated nodes sharing one IP
        each answer only their own."""
        out = []
        for node_id, node in sorted(self.nodes.items()):
            if node.status(now) == NodeStatus.OFFLINE:
                continue
            header = self._header(p.MsgType.PING, node_id, now)
            out.append((p.encode(header, p.Ping(int(now * 1e6))), (node.address[0], port)))
        return out

    def _header(self, msg_type: p.MsgType, node_id: int, now: float) -> p.Header:
        header = p.Header(msg_type, node_id, self.seq, int(now * 1000) % _SEQ_MOD)
        self.seq = (self.seq + 1) % _SEQ_MOD
        return header

    # ---- CONFIG delivery (docs/protocol.md section 5) ----------------------

    def set_config(self, node_id: int, now: float, **fields) -> p.Config:
        """Start sending a new configuration to a node. Fields not given keep
        the value the PC last chose for that node (or the protocol default).
        Raises KeyError for an unknown node and ValueError for a bad value."""
        node = self.nodes[node_id]
        base = node.config.config if node.config else p.Config(0)
        unknown = set(fields) - (set(vars(base)) - {"config_version"})  # The PC picks versions
        if unknown:
            raise ValueError(f"cannot set {', '.join(sorted(unknown))}")
        config = p.Config(**(vars(base) | fields | {"config_version": self._next_version(node)}))
        if config.check() != p.AckStatus.OK:
            raise ValueError(f"value out of range: {fields}")
        node.config = ConfigDelivery(config, next_send=now)
        self.messages.append(f"node {node_id}: sending CONFIG {config.config_version}")
        return config

    @staticmethod
    def _next_version(node: NodeState) -> int:
        """Higher than anything the PC sent or the node reports, so the node
        never refuses it as STALE_VERSION (unless the PC has restarted and the
        node hasn't reported yet)."""
        sent = node.config.config.config_version if node.config else 0
        reported = node.telemetry.config_version if node.telemetry else 0
        version = max(sent, reported) + 1
        if version > 0xFFFF:
            raise ValueError("config_version exhausted; reboot the node to reset it")
        return version

    def config_sends(self, now: float, port: int = p.PORT_CONFIG) -> list[tuple[bytes, Address]]:
        """CONFIG datagrams due now: first sends and retries."""
        out = []
        for node_id, node in sorted(self.nodes.items()):
            d = node.config
            if d is None or d.state != ConfigState.SENDING or now < d.next_send:
                continue
            if d.sends >= CONFIG_MAX_SENDS:
                d.state, d.next_send = ConfigState.FAILED, now + CONFIG_FAILED_WAIT_S
                self.messages.append(f"node {node_id}: CONFIG {d.config.config_version} "
                                     f"not acknowledged after {d.sends} sends")
                continue
            d.sends += 1
            d.next_send = now + CONFIG_RETRY_S
            header = self._header(p.MsgType.CONFIG, node_id, now)
            out.append((p.encode(header, d.config), (node.address[0], port)))
        return out

    def _config_acked(self, node: NodeState, header: p.Header, ack: p.ConfigAck,
                      now: float) -> None:
        d = node.config
        if d is None or ack.config_version != d.config.config_version:
            return  # Answer to an older CONFIG
        d.status = ack.status
        if d.state != ConfigState.SENDING:
            return  # Duplicate ACK from a retry
        if ack.status == p.AckStatus.OK:
            self._applied(node, header.seq)
        elif ack.status == p.AckStatus.STALE_VERSION:
            # The node has a newer version than we know of (the PC restarted
            # before it reported). Jump past it and send again.
            d.config.config_version = self._next_version(node)
            d.sends, d.next_send = 0, now
            self.messages.append(f"node {node.node_id}: stale version, resending as "
                                 f"CONFIG {d.config.config_version}")
        else:
            d.state = ConfigState.REJECTED
            self.messages.append(f"node {node.node_id}: CONFIG {ack.config_version} "
                                 f"rejected ({ack.status.name})")

    def _applied(self, node: NodeState, seq: int) -> None:
        d = node.config
        if d.state != ConfigState.APPLIED:
            self.messages.append(f"node {node.node_id}: CONFIG {d.config.config_version} applied")
        d.state, d.confirmed_seq = ConfigState.APPLIED, seq
        node.report_interval_ms = d.config.report_interval_ms

    def _check_config(self, node: NodeState, header: p.Header, t: p.Telemetry,
                      now: float) -> None:
        """Self-healing: TELEMETRY says which config the node is running."""
        d = node.config
        if d is None or d.state == ConfigState.REJECTED:
            return
        if t.config_version == d.config.config_version:
            if d.state != ConfigState.APPLIED:  # Applied, but the ACK was lost
                self._applied(node, header.seq)
            return
        if d.state == ConfigState.SENDING:
            return
        sent_after_confirmation = d.confirmed_seq is None or _seq_after(header.seq, d.confirmed_seq)
        if not sent_after_confirmation or (d.state == ConfigState.FAILED and now < d.next_send):
            return
        # Typically the node rebooted and is back on defaults (version 0).
        if t.config_version > d.config.config_version:
            d.config.config_version = self._next_version(node)
        d.state, d.sends, d.next_send, d.confirmed_seq = ConfigState.SENDING, 0, now, None
        self.messages.append(f"node {node.node_id} runs config {t.config_version}: "
                             f"resending CONFIG {d.config.config_version}")

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
    audio = t.latest_audio
    parts.append(f"{audio.audio_class.name} {audio.confidence_pct}%" if audio else "audio --")
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
    "temperature_c", "humidity_pct", "dsp_time_us", "inference_time_us",
    "free_heap_bytes", "co2_ppm", "config_version", "audio_overruns", "audio_window_seq",
    "audio_classes", "audio_prob_pct", "audio_rms", "pir_active_pct", "valid_flags",
    "cpu_load_pct", "wifi_rssi_dbm",
]


def csv_row(header: p.Header, t: p.Telemetry) -> list:
    return [
        datetime.now().isoformat(timespec="milliseconds"), header.node_id, header.seq,
        header.sender_time_ms, header.flags, f"{t.temperature_c:.1f}",
        f"{t.humidity_pct:.1f}", t.dsp_time_us, t.inference_time_us,
        t.free_heap_bytes, t.co2_ppm, t.config_version, t.audio_overruns, t.audio_window_seq,
        # One entry per audio window, oldest first, separated by ";"
        ";".join(w.audio_class.name for w in t.audio),
        ";".join("/".join(map(str, w.prob_pct)) for w in t.audio),
        ";".join(f"{w.rms:.4f}" for w in t.audio),
        t.pir_active_pct, int(t.valid_flags), t.cpu_load_pct, t.wifi_rssi_dbm,
    ]


class GatewayServer:
    """The gateway on a UDP socket. Call poll() in a loop, or run()."""

    def __init__(self, bind: Address = ("0.0.0.0", p.PORT_TELEMETRY),
                 config_port: int = p.PORT_CONFIG, ping_interval: float = PING_INTERVAL_S,
                 summary_interval: float = SUMMARY_INTERVAL_S,
                 csv_file: Optional[TextIO] = None, out: TextIO = sys.stdout,
                 fusion: Optional[FusionEngine] = None) -> None:
        self.gateway = Gateway()
        self.fusion = fusion  # Classroom states; None to only receive
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
        # Held while processing, so another thread (the dashboard's web
        # server) can read self.gateway safely.
        self.lock = threading.Lock()
        # Called as listener(header, telemetry, now) for every TELEMETRY.
        self.telemetry_listeners: list[Callable[[p.Header, p.Telemetry, float], None]] = []

    def poll(self, timeout: float = 0.2) -> None:
        readable, _, _ = select.select([self.sock], [], [], timeout)
        data = None
        if readable:
            try:
                data, address = self.sock.recvfrom(p.MAX_DATAGRAM + 1)
            except ConnectionResetError:
                # Windows reports an ICMP "port unreachable" for an earlier
                # PING here (WSAECONNRESET). Harmless: the node is offline.
                pass
        with self.lock:
            if data is not None:
                self._received(data, address, time.monotonic())
            now = time.monotonic()
            for node_id, status in self.gateway.status_changes(now):
                self._print(f"node {node_id} is now {status.value}")
            if now >= self._next_ping:
                self.send_pings()
                self._next_ping = now + self.ping_interval
            self._send_all(self.gateway.config_sends(now, self.config_port), "CONFIG")
            if self.fusion:
                self._evaluate_fusion(now)
            for message in self.gateway.messages:
                self._print(message)
            self.gateway.messages.clear()
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
            if self.fusion:
                self.fusion.add(header.node_id, payload, now)
            for listener in self.telemetry_listeners:
                listener(header, payload, now)
        elif isinstance(payload, p.ConfigAck):
            self._print(f"node {header.node_id} CONFIG_ACK version "
                        f"{payload.config_version}: {payload.status.name}")

    def _evaluate_fusion(self, now: float) -> None:
        statuses = {node_id: node.status(now) for node_id, node in self.gateway.nodes.items()}
        self.fusion.evaluate(
            now,
            online={n for n, s in statuses.items() if s == NodeStatus.ONLINE},
            stale={n for n, s in statuses.items() if s == NodeStatus.STALE})
        for event in self.fusion.drain_events():
            self._print("classroom " + format_event(event))

    def set_mode(self, mode: p.Mode) -> list[int]:
        """Change the classroom mode: fusion rules switch at once, and every
        known node gets a CONFIG with the new mode. Returns those node IDs."""
        with self.lock:
            now = time.monotonic()
            if self.fusion:
                self.fusion.set_mode(mode, now)
            nodes = sorted(self.gateway.nodes)
            for node_id in nodes:
                self.gateway.set_config(node_id, now, mode=mode)
            return nodes

    def send_pings(self) -> None:
        self._send_all(self.gateway.pings(time.monotonic(), self.config_port), "PING")

    def set_config(self, node_id: int, **fields) -> p.Config:
        """Thread-safe Gateway.set_config(); the next poll() sends it."""
        with self.lock:
            return self.gateway.set_config(node_id, time.monotonic(), **fields)

    def _send_all(self, datagrams: list[tuple[bytes, Address]], what: str) -> None:
        for data, address in datagrams:
            try:
                self.sock.sendto(data, address)
            except OSError as e:  # e.g. network unreachable; retried on the next round
                self._print(f"{what} to {address[0]} failed: {e}")

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


def add_fusion_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fusion-config", metavar="FILE",
                        help="JSON overriding fusion thresholds, zones or mode (see fusion.py)")


def load_fusion_config(parser: argparse.ArgumentParser, path: Optional[str]) -> FusionConfig:
    try:
        return FusionConfig.from_json(path) if path else FusionConfig()
    except (OSError, ValueError, KeyError, TypeError) as e:
        parser.error(f"--fusion-config: {e}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="MOSAIC PC gateway (protocol v2)")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on")
    parser.add_argument("--port", type=int, default=p.PORT_TELEMETRY)
    parser.add_argument("--node-port", type=int, default=p.PORT_CONFIG,
                        help="port nodes listen on for PING/CONFIG")
    parser.add_argument("--ping-interval", type=float, default=PING_INTERVAL_S)
    parser.add_argument("--csv", metavar="FILE", help="append every TELEMETRY to this CSV")
    add_fusion_argument(parser)
    args = parser.parse_args(argv)

    fusion = FusionEngine(load_fusion_config(parser, args.fusion_config))
    csv_file = open(args.csv, "a", newline="") if args.csv else None
    server = GatewayServer((args.host, args.port), args.node_port, args.ping_interval,
                           csv_file=csv_file, fusion=fusion)
    try:
        server.run()
    finally:
        server.close()
        if csv_file:
            csv_file.close()


if __name__ == "__main__":
    main()
