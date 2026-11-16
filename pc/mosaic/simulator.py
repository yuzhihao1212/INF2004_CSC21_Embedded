"""Simulated MOSAIC nodes speaking protocol v2, for testing the PC gateway
without hardware. Replaces pc/prototype/simulate_nodesender.py, which sends
the old text format.

Run from the pc/ folder, next to  python -m mosaic.gateway :
    python -m mosaic.simulator --nodes 3
    python -m mosaic.simulator --loss 0.1 --reboot-every 30
    python -m mosaic.simulator --nodes 4 --scenario lecture   # see scenarios.py

Without --scenario, readings and audio classes are random. With one, the
nodes play a scripted classroom (lecture, chatter, poor ventilation, ...)
so the fusion engine's states can be demonstrated without hardware.

All simulated nodes share one socket on the node port (5006). Each answers
only the PINGs and CONFIGs addressed to its node ID, as a real node does.

With --mqtt HOST[:PORT] the nodes talk through an MQTT broker instead, as the
micro T-Kernel node does: each simulated node is its own MQTT client with its
own last will (topics in mosaic/mqtt.py).
"""

from __future__ import annotations

import argparse
import heapq
import math
import random
import select
import socket
import time
from dataclasses import dataclass
from typing import Optional

from mosaic import mqtt
from mosaic import protocol as p
from mosaic import scenarios

CO2_WARMUP_S = 10.0  # Real ACD1100 is 120 s; shortened so tests see both states
DRIFT = 1 / 30       # Per report, CO2 and temperature move this share of the way to target


@dataclass
class SimNode:
    node_id: int
    boot_time: Optional[float] = None
    seq: int = 0
    first: bool = True
    config_version: int = 0
    audio_window_seq: int = 0
    temperature_c: float = 25.0
    humidity_pct: float = 60.0
    co2_ppm: float = 600.0
    audio_phase_s: float = 0.0
    report_phase_s: float = 0.0
    audio_period_s: float = 0.5
    report_interval_s: float = 1.0
    next_report: Optional[float] = None
    last_audio_index: int = -1
    seen_jumps: int = 0

    def header(self, msg_type: p.MsgType, now: float) -> p.Header:
        if self.boot_time is None:
            self.boot_time = now
        flags = p.FLAG_FIRST_SINCE_BOOT if self.first and msg_type == p.MsgType.TELEMETRY else 0
        header = p.Header(msg_type, self.node_id, self.seq,
                          int((now - self.boot_time) * 1000) % (1 << 32), flags)
        self.seq = (self.seq + 1) % (1 << 32)
        if msg_type == p.MsgType.TELEMETRY:
            self.first = False
        return header

    def reboot(self) -> None:
        self.boot_time, self.seq, self.first, self.config_version = None, 0, True, 0
        self.audio_window_seq = 0


class Simulator:
    def __init__(self, nodes: int = 3, seed: Optional[int] = None, loss: float = 0.0,
                 warmup_s: float = CO2_WARMUP_S,
                 scenario: Optional[scenarios.Scenario] = None, *, aligned: bool = False,
                 receive_jitter_s: float = 0.0, report_interval_s: float = 1.0,
                 phases: Optional[dict[int, tuple[float, float]]] = None,
                 clock: Optional[scenarios.ScriptClock] = None) -> None:
        """Independent audio/report clocks by default; aligned=True is a test fixture.

        poll(now) returns (receive_time, datagram) deliveries, including uniform
        0..receive_jitter_s network delay. Consumers must use those receive times,
        not the time they happen to poll. Timing has its own seeded RNG so sensor
        noise cannot accidentally change the clock phases or network jitter.
        phases overrides (audio phase, report phase) for reproducible fault cases.
        clock is a shared script clock (the dashboard's demo controls); by
        default the simulator keeps its own, started on the first poll.
        """
        if (not math.isfinite(receive_jitter_s) or not math.isfinite(report_interval_s)
                or receive_jitter_s < 0 or report_interval_s <= 0):
            raise ValueError("jitter must be nonnegative and report interval positive")
        self.nodes = [SimNode(i) for i in range(1, nodes + 1)]
        self.rng = random.Random(seed)
        self.timing_rng = random.Random(seed)
        self.aligned = aligned
        self.receive_jitter_s = receive_jitter_s
        for node in self.nodes:
            node.report_interval_s = report_interval_s
            if aligned:
                node.last_audio_index = -2  # Legacy fixture starts with two completed windows.
            else:
                node.audio_phase_s = self.timing_rng.uniform(0, 0.5)
                node.report_phase_s = self.timing_rng.uniform(0, report_interval_s)
                node.audio_period_s *= 1 + self.timing_rng.uniform(-100, 100) * 1e-6
            if phases and node.node_id in phases:
                node.audio_phase_s, node.report_phase_s = phases[node.node_id]
                node.audio_period_s = 0.5
        self.loss = loss
        self.warmup_s = warmup_s
        self.scenario = scenario
        self.clock = clock or (scenarios.ScriptClock(scenario) if scenario else None)
        self.start: Optional[float] = None  # Shared physical simulation epoch, not Pico clocks.
        self._deliveries: list[tuple[float, int, bytes]] = []
        self._delivery_order = 0

    def phase(self, now: float) -> Optional[tuple[int, scenarios.Phase]]:
        """The scenario phase being played at `now`, or None without a scenario."""
        if self.clock is None:
            return None
        if self.start is None:
            self.start = now
            self.clock.start(now)
        return self.clock.phase(now)

    def telemetry(self, now: float) -> list[bytes]:
        """Datagrams due by now; use poll() when exact receive times matter."""
        return [data for _, data in self.poll(now)]

    def poll(self, now: float) -> list[tuple[float, bytes]]:
        if self.start is None:
            self.start = now
            if self.clock:
                self.clock.start(now)
        for node in self.nodes:
            if node.next_report is None:
                node.next_report = self.start + node.report_phase_s
        # Generate in send order so advancing virtual time in larger steps does
        # not change RNG consumption, payloads or delivery order.
        while min(node.next_report for node in self.nodes) <= now + 1e-9:
            node = min(self.nodes, key=lambda n: (n.next_report, n.node_id))
            sent = node.next_report
            header = node.header(p.MsgType.TELEMETRY, sent)
            index = math.floor((sent - self.start - node.audio_phase_s) / node.audio_period_s + 1e-9)
            completed = max(0, index - node.last_audio_index)
            times = tuple(self.start + node.audio_phase_s + i * node.audio_period_s
                          for i in range(max(node.last_audio_index + 1, index - 1), index + 1))
            node.last_audio_index = index
            node.audio_window_seq = (node.audio_window_seq + completed) % 65536
            payload = self._readings(node, sent, times)
            received = sent + self.timing_rng.uniform(0, self.receive_jitter_s)
            if self.rng.random() >= self.loss:
                heapq.heappush(self._deliveries, (received, self._delivery_order, p.encode(header, payload)))
                self._delivery_order += 1
            node.next_report += node.report_interval_s
        out = []
        while self._deliveries and self._deliveries[0][0] <= now + 1e-9:
            received, _, data = heapq.heappop(self._deliveries)
            out.append((received, data))
        return out

    def next_event(self) -> float:
        """Next send or receive deadline after poll(); used by the socket loop."""
        return min([n.next_report for n in self.nodes]
                   + ([self._deliveries[0][0]] if self._deliveries else []))

    def _readings(self, node: SimNode, now: float, window_times: tuple[float, ...]) -> p.Telemetry:
        rng = self.rng
        phase = self.phase(now)
        if phase is None:  # Random walk
            node.temperature_c = min(30.0, max(22.0, node.temperature_c + rng.gauss(0, 0.05)))
            node.humidity_pct = min(80.0, max(40.0, node.humidity_pct + rng.gauss(0, 0.2)))
            node.co2_ppm = min(2000.0, max(420.0, node.co2_ppm + rng.gauss(1.0, 5.0)))
            windows = tuple(self._audio_window() for _ in window_times)
            pir = rng.choice([0, 0, 10, 40, 80, 100])
        else:
            zone = phase[1].zone(node.node_id)
            if node.seen_jumps != self.clock.jumps:  # Skipped ahead: the room is already in the new phase
                node.seen_jumps = self.clock.jumps
                node.temperature_c, node.humidity_pct = zone.temperature_c, zone.humidity_pct
                node.co2_ppm = zone.co2_ppm
            drift = 1 - (1 - DRIFT) ** self.clock.drift_rate  # Same catch-up per script second at 2x and 4x
            node.temperature_c += (zone.temperature_c - node.temperature_c) * drift + rng.gauss(0, 0.03)
            node.humidity_pct += (zone.humidity_pct - node.humidity_pct) * drift + rng.gauss(0, 0.1)
            node.co2_ppm += (zone.co2_ppm - node.co2_ppm) * drift + rng.gauss(0, 3.0)
            # Audio is stamped from its TRUE completion time, before report
            # batching/jitter. All nodes hear the same lecturer envelope, sampled
            # on their independent audio clocks. Phase transitions are not dated
            # from when a delayed report happens to reach the PC.
            windows = []
            for completed_at in window_times:
                audio_zone = self.phase(completed_at)[1].zone(node.node_id)
                rms = audio_zone.rms
                if rms is not None:
                    rms *= 1 + 0.25 * math.sin((completed_at - self.start) * 0.8)
                windows.append(self._audio_window(audio_zone.probs, rms))
            windows = tuple(windows)
            pir = round(min(100.0, max(0.0, rng.gauss(zone.pir_pct, zone.pir_pct * 0.3))))

        valid = p.Valid.TEMP_HUM | p.Valid.PIR
        warming = now - node.boot_time < self.warmup_s
        valid |= p.Valid.CO2_WARMUP if warming else p.Valid.CO2
        return p.Telemetry(
            temperature_x10=round(node.temperature_c * 10),
            humidity_x10=round(node.humidity_pct * 10),
            dsp_time_us=rng.randint(75000, 90000),
            inference_time_us=rng.randint(800, 1200),
            free_heap_bytes=rng.randint(60000, 70000),
            co2_ppm=0 if warming else int(node.co2_ppm),
            config_version=node.config_version,
            audio_window_seq=node.audio_window_seq,
            audio=windows,
            pir_active_pct=pir,
            valid_flags=valid,
            cpu_load_pct=rng.randint(40, 70),
            wifi_rssi_dbm=rng.randint(-70, -50),
        )

    def _audio_window(self, mix: Optional[tuple[int, ...]] = None,
                      rms: Optional[float] = None) -> p.AudioWindow:
        """A classified window: random, or near the given class mix (%)."""
        rng = self.rng
        classes = (p.AudioClass.BACKGROUND_NOISE, p.AudioClass.SPEECH, p.AudioClass.TRANSIENT_NOISE)
        if mix is None:
            weights = [rng.random() for _ in classes]
            weights[rng.randrange(len(classes))] += 2.0  # One class usually dominates
        else:
            weights = [max(0.5, rng.gauss(mix[cls - 1], 5.0)) for cls in classes]
        probs = [0] * p.AUDIO_CLASS_COUNT
        for cls, weight in zip(classes, weights):
            probs[cls - 1] = int(100 * weight / sum(weights))
        best = max(classes, key=lambda cls: probs[cls - 1])
        audio_class = best if probs[best - 1] >= 60 else p.AudioClass.UNKNOWN
        level = rng.randint(5 * 16, 60 * 16) if rms is None else round(rms * 16)
        return p.AudioWindow(level, audio_class, tuple(probs))

    def handle(self, data: bytes, now: float) -> list[bytes]:
        """The addressed node's reply to a PING or CONFIG; [] for anything else."""
        try:
            header, payload = p.decode(data)
        except p.ProtocolError:
            return []
        replies = []
        for node in self.nodes:
            if node.node_id != header.node_id:  # Addressed to another node
                continue
            if isinstance(payload, p.Config):  # Same rules as the node firmware
                status = payload.check(node.config_version)
                if status == p.AckStatus.OK:
                    node.config_version = payload.config_version
                    node.report_interval_s = payload.report_interval_ms / 1000
                    node.next_report = now + node.report_interval_s
                ack = p.ConfigAck(payload.config_version, status)
                replies.append(p.encode(node.header(p.MsgType.CONFIG_ACK, now), ack))
            elif header.msg_type == p.MsgType.PING:
                replies.append(p.encode(node.header(p.MsgType.PONG, now), payload))
        return replies


def add_scenario_argument(parser: argparse.ArgumentParser) -> None:
    names = ", ".join(f"{name} ({s.seconds / 60:.0f} min)" for name, s in scenarios.SCENARIOS.items())
    parser.add_argument("--scenario", choices=scenarios.SCENARIOS, metavar="NAME",
                        help=f"play a scripted classroom: {names}")


def add_timing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--aligned", action="store_true", help="align simulated clocks (test fixture)")
    parser.add_argument("--receive-jitter-ms", type=float, default=0,
                        help="uniform simulated receive delay from 0 to this many milliseconds")


class UdpLink:
    """All simulated nodes on one UDP socket, sending straight to the PC."""

    def __init__(self, pc: tuple[str, int], listen_port: int) -> None:
        self.pc = pc
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", listen_port))

    def describe(self) -> str:
        return f"{self.pc[0]}:{self.pc[1]}, listening on {self.sock.getsockname()[1]}"

    def send(self, data: bytes) -> None:
        self.sock.sendto(data, self.pc)

    def wait(self, timeout: float) -> list[tuple[bytes, object]]:
        """Packets for the nodes within timeout, each with a reply function."""
        readable, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if not readable:
            return []
        try:
            data, source = self.sock.recvfrom(p.MAX_DATAGRAM + 1)
        except ConnectionResetError:  # Windows: gateway not running yet
            return []
        return [(data, lambda reply: self.sock.sendto(reply, source))]

    def close(self) -> None:
        self.sock.close()


class MqttLink:
    """One MQTT client per simulated node, each with an 'offline' last will."""

    def __init__(self, host: str, port: int, node_ids: list[int]) -> None:
        self.host, self.port = host, port
        self.clients = {n: mqtt.MqttClient(host, port, client_id=f"mosaic-sim-node{n}",
                                           will=(mqtt.status_topic(n), b"offline", 1, True))
                        for n in node_ids}
        self._retry_at = 0.0
        for node_id in self.clients:
            self._connect(node_id)

    def describe(self) -> str:
        return f"MQTT broker {self.host}:{self.port}"

    def _connect(self, node_id: int) -> None:
        client = self.clients[node_id]
        try:
            client.connect()
            client.subscribe(mqtt.config_topic(node_id), qos=1)
            client.publish(mqtt.status_topic(node_id), b"online", qos=1, retain=True)
        except (OSError, mqtt.MqttError) as e:
            client._drop()
            self._retry_at = time.monotonic() + mqtt.RECONNECT_S
            print(f"node {node_id}: cannot reach {self.describe()}: {e}", flush=True)

    def send(self, data: bytes) -> None:
        header, _ = p.decode(data)
        client = self.clients[header.node_id]
        if client.connected:
            try:
                client.publish(mqtt.telemetry_topic(header.node_id), data)
            except ConnectionError:
                pass  # Lost, like a datagram; reconnected below

    def wait(self, timeout: float) -> list[tuple[bytes, object]]:
        now = time.monotonic()
        for node_id, client in self.clients.items():
            if not client.connected and now >= self._retry_at:
                self._connect(node_id)
            try:
                client.tick(now)
            except ConnectionError:
                pass
        live = [c for c in self.clients.values() if c.connected]
        if not live:
            time.sleep(max(0.0, timeout))
            return []
        readable, _, _ = select.select(live, [], [], max(0.0, timeout))
        out = []
        for client in readable:
            try:
                messages = client.read()
            except ConnectionError:
                continue
            for m in messages:
                node_id = mqtt.topic_node(m.topic, "config")
                if node_id is None:
                    continue
                out.append((m.payload, lambda reply, n=node_id, c=client: self._reply(c, n, reply)))
        return out

    @staticmethod
    def _reply(client: mqtt.MqttClient, node_id: int, data: bytes) -> None:
        try:
            client.publish(mqtt.telemetry_topic(node_id), data)
        except ConnectionError:
            pass  # Lost, like a datagram

    def close(self) -> None:
        for client in self.clients.values():
            client.close()


def main(argv: Optional[list[str]] = None, clock: Optional[scenarios.ScriptClock] = None) -> None:
    parser = argparse.ArgumentParser(description="Simulated MOSAIC nodes (protocol v2)")
    parser.add_argument("--pc-ip", default="127.0.0.1")
    parser.add_argument("--pc-port", type=int, default=p.PORT_TELEMETRY)
    parser.add_argument("--listen-port", type=int, default=p.PORT_CONFIG)
    parser.add_argument("--nodes", type=int, default=3, choices=range(1, p.MAX_NODES + 1),
                        metavar=f"1..{p.MAX_NODES}")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between reports")
    parser.add_argument("--loss", type=float, default=0.0, help="fraction of TELEMETRY to drop")
    parser.add_argument("--reboot-every", type=float, default=0.0, metavar="S",
                        help="reboot a random node every S seconds (0 = never)")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mqtt", metavar="HOST[:PORT]",
                        help="send through this MQTT broker instead of UDP to --pc-ip")
    add_scenario_argument(parser)
    add_timing_arguments(parser)
    args = parser.parse_args(argv)

    if args.receive_jitter_ms < 0 or args.interval <= 0:
        parser.error("jitter must be nonnegative and interval positive")
    sim = Simulator(args.nodes, args.seed, args.loss, scenario=scenarios.get(args.scenario),
                    aligned=args.aligned, receive_jitter_s=args.receive_jitter_ms / 1000,
                    report_interval_s=args.interval, clock=clock)
    if sim.scenario:
        print(f"Scenario {args.scenario} ({sim.scenario.seconds / 60:.0f} min): "
              f"{sim.scenario.description}")
    if args.mqtt:
        try:
            host, port = mqtt.parse_broker(args.mqtt)
        except ValueError as e:
            parser.error(f"--mqtt: {e}")
        link = MqttLink(host, port, [n.node_id for n in sim.nodes])
    else:
        link = UdpLink((args.pc_ip, args.pc_port), args.listen_port)
    print(f"{args.nodes} simulated node(s) -> {link.describe()} (Ctrl+C to stop)")

    now = time.monotonic()
    next_reboot = now + args.reboot_every if args.reboot_every else None
    last_phase = None
    try:
        while True:
            now = time.monotonic()
            for received, data in sim.poll(now):
                link.send(data)
            phase = sim.phase(now)
            if phase and phase[0] != last_phase:
                last_phase = phase[0]
                print(f"[{phase[0] + 1}/{len(sim.scenario.phases)}] {phase[1].label} "
                      f"({phase[1].seconds:.0f} s) -> expect {phase[1].expect}", flush=True)
            if next_reboot is not None and now >= next_reboot:
                node = sim.rng.choice(sim.nodes)
                node.reboot()
                print(f"node {node.node_id} rebooted")
                next_reboot += args.reboot_every
            deadline = min(sim.next_event(), next_reboot or float("inf"))
            for data, reply in link.wait(deadline - time.monotonic()):
                for answer in sim.handle(data, time.monotonic()):
                    reply(answer)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()

if __name__ == "__main__":
    main()
