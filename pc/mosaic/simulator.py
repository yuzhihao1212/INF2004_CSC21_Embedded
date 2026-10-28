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
"""

from __future__ import annotations

import argparse
import random
import select
import socket
import time
from dataclasses import dataclass
from typing import Optional

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


class Simulator:
    def __init__(self, nodes: int = 3, seed: Optional[int] = None, loss: float = 0.0,
                 warmup_s: float = CO2_WARMUP_S,
                 scenario: Optional[scenarios.Scenario] = None) -> None:
        self.nodes = [SimNode(i) for i in range(1, nodes + 1)]
        self.rng = random.Random(seed)
        self.loss = loss
        self.warmup_s = warmup_s
        self.scenario = scenario
        self.start: Optional[float] = None  # Time of the first report

    def phase(self, now: float) -> Optional[tuple[int, scenarios.Phase]]:
        """The scenario phase being played at `now`, or None without a scenario."""
        if self.scenario is None:
            return None
        if self.start is None:
            self.start = now
        return self.scenario.phase_at(now - self.start)

    def telemetry(self, now: float) -> list[bytes]:
        """One TELEMETRY per node. A 'lost' datagram still uses up a seq,
        as on a real node whose packet is lost in the air."""
        out = []
        for node in self.nodes:
            header = node.header(p.MsgType.TELEMETRY, now)
            payload = self._readings(node, now)
            if self.rng.random() >= self.loss:
                out.append(p.encode(header, payload))
        return out

    def _readings(self, node: SimNode, now: float) -> p.Telemetry:
        rng = self.rng
        phase = self.phase(now)
        if phase is None:  # Random walk
            node.temperature_c = min(30.0, max(22.0, node.temperature_c + rng.gauss(0, 0.05)))
            node.humidity_pct = min(80.0, max(40.0, node.humidity_pct + rng.gauss(0, 0.2)))
            node.co2_ppm = min(2000.0, max(420.0, node.co2_ppm + rng.gauss(1.0, 5.0)))
            windows = tuple(self._audio_window() for _ in range(p.AUDIO_WINDOWS_PER_REPORT))
            pir = rng.choice([0, 0, 10, 40, 80, 100])
        else:
            zone = phase[1].zone(node.node_id)
            node.temperature_c += (zone.temperature_c - node.temperature_c) * DRIFT + rng.gauss(0, 0.03)
            node.humidity_pct += (zone.humidity_pct - node.humidity_pct) * DRIFT + rng.gauss(0, 0.1)
            node.co2_ppm += (zone.co2_ppm - node.co2_ppm) * DRIFT + rng.gauss(0, 3.0)
            windows = tuple(self._audio_window(zone.probs)
                            for _ in range(p.AUDIO_WINDOWS_PER_REPORT))
            pir = round(min(100.0, max(0.0, rng.gauss(zone.pir_pct, zone.pir_pct * 0.3))))

        node.audio_window_seq = (node.audio_window_seq + len(windows)) % (1 << 16)

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

    def _audio_window(self, mix: Optional[tuple[int, ...]] = None) -> p.AudioWindow:
        """A classified window: random, or near the given class mix (%)."""
        rng = self.rng
        if mix is None:
            weights = [rng.random() for _ in range(p.AUDIO_CLASS_COUNT)]
            weights[rng.randrange(p.AUDIO_CLASS_COUNT)] += 2.0  # One class usually dominates
        else:
            weights = [max(0.5, rng.gauss(share, 5.0)) for share in mix]
        probs = [int(100 * w / sum(weights)) for w in weights]
        best = max(range(p.AUDIO_CLASS_COUNT), key=probs.__getitem__)
        audio_class = p.AudioClass(best + 1) if probs[best] >= 60 else p.AudioClass.UNKNOWN
        return p.AudioWindow(rng.randint(5 * 16, 60 * 16), audio_class, tuple(probs))

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
                ack = p.ConfigAck(payload.config_version, status)
                replies.append(p.encode(node.header(p.MsgType.CONFIG_ACK, now), ack))
            elif header.msg_type == p.MsgType.PING:
                replies.append(p.encode(node.header(p.MsgType.PONG, now), payload))
        return replies


def add_scenario_argument(parser: argparse.ArgumentParser) -> None:
    names = ", ".join(f"{name} ({s.seconds / 60:.0f} min)" for name, s in scenarios.SCENARIOS.items())
    parser.add_argument("--scenario", choices=scenarios.SCENARIOS, metavar="NAME",
                        help=f"play a scripted classroom: {names}")


def main(argv: Optional[list[str]] = None) -> None:
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
    add_scenario_argument(parser)
    args = parser.parse_args(argv)

    sim = Simulator(args.nodes, args.seed, args.loss, scenario=scenarios.get(args.scenario))
    if sim.scenario:
        print(f"Scenario {args.scenario} ({sim.scenario.seconds / 60:.0f} min): "
              f"{sim.scenario.description}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.listen_port))
    pc = (args.pc_ip, args.pc_port)
    print(f"{args.nodes} simulated node(s) -> {pc[0]}:{pc[1]}, "
          f"listening on {args.listen_port} (Ctrl+C to stop)")

    now = time.monotonic()
    next_report = now
    next_reboot = now + args.reboot_every if args.reboot_every else None
    last_phase = None
    try:
        while True:
            now = time.monotonic()
            if now >= next_report:
                for data in sim.telemetry(now):
                    sock.sendto(data, pc)
                next_report += args.interval
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
            readable, _, _ = select.select([sock], [], [], max(0.0, next_report - now))
            if readable:
                try:
                    data, source = sock.recvfrom(p.MAX_DATAGRAM + 1)
                except ConnectionResetError:  # Windows: gateway not running yet
                    continue
                for reply in sim.handle(data, time.monotonic()):
                    sock.sendto(reply, source)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
