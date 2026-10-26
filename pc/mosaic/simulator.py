"""Simulated MOSAIC nodes speaking protocol v1, for testing the PC gateway
without hardware. Replaces pc/prototype/simulate_nodesender.py, which sends
the old text format.

Run from the pc/ folder, next to  python -m mosaic.gateway :
    python -m mosaic.simulator --nodes 3
    python -m mosaic.simulator --loss 0.1 --reboot-every 30

All simulated nodes share one socket on the node port (5006), so they answer
every PING and CONFIG together. Real nodes each have their own IP.
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

CO2_WARMUP_S = 10.0  # Real ACD1100 is 120 s; shortened so tests see both states


@dataclass
class SimNode:
    node_id: int
    boot_time: Optional[float] = None
    seq: int = 0
    first: bool = True
    config_version: int = 0
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
                 warmup_s: float = CO2_WARMUP_S) -> None:
        self.nodes = [SimNode(i) for i in range(1, nodes + 1)]
        self.rng = random.Random(seed)
        self.loss = loss
        self.warmup_s = warmup_s

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
        node.temperature_c = min(30.0, max(22.0, node.temperature_c + rng.gauss(0, 0.05)))
        node.humidity_pct = min(80.0, max(40.0, node.humidity_pct + rng.gauss(0, 0.2)))
        node.co2_ppm = min(2000.0, max(420.0, node.co2_ppm + rng.gauss(1.0, 5.0)))

        weights = [rng.random() for _ in range(p.AUDIO_CLASS_COUNT)]
        weights[rng.randrange(p.AUDIO_CLASS_COUNT)] += 2.0  # One class usually dominates
        probs = [int(100 * w / sum(weights)) for w in weights]
        best = max(range(p.AUDIO_CLASS_COUNT), key=probs.__getitem__)
        audio_class = p.AudioClass(best + 1) if probs[best] >= 60 else p.AudioClass.UNKNOWN

        valid = p.Valid.TEMP_HUM | p.Valid.PIR | p.Valid.AUDIO
        warming = now - node.boot_time < self.warmup_s
        valid |= p.Valid.CO2_WARMUP if warming else p.Valid.CO2
        return p.Telemetry(
            temperature_c=round(node.temperature_c, 1),
            humidity_pct=round(node.humidity_pct, 1),
            audio_rms=round(rng.uniform(5.0, 60.0), 2),
            dsp_time_us=rng.randint(75000, 90000),
            inference_time_us=rng.randint(800, 1200),
            free_heap_bytes=rng.randint(60000, 70000),
            co2_ppm=0 if warming else int(node.co2_ppm),
            config_version=node.config_version,
            audio_class=audio_class,
            pir_active_pct=rng.choice([0, 0, 10, 40, 80, 100]),
            audio_prob_pct=tuple(probs),
            valid_flags=valid,
            cpu_load_pct=rng.randint(40, 70),
            wifi_rssi_dbm=rng.randint(-70, -50),
        )

    def handle(self, data: bytes, now: float) -> list[bytes]:
        """Replies from every node to a PING or CONFIG; [] for anything else."""
        try:
            header, payload = p.decode(data)
        except p.ProtocolError:
            return []
        replies = []
        for node in self.nodes:
            if isinstance(payload, p.Config):  # Same rules as the node firmware
                status = payload.check()
                if status == p.AckStatus.OK:
                    node.config_version = payload.config_version
                ack = p.ConfigAck(payload.config_version, status)
                replies.append(p.encode(node.header(p.MsgType.CONFIG_ACK, now), ack))
            elif header.msg_type == p.MsgType.PING:
                replies.append(p.encode(node.header(p.MsgType.PONG, now), payload))
        return replies


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Simulated MOSAIC nodes (protocol v1)")
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
    args = parser.parse_args(argv)

    sim = Simulator(args.nodes, args.seed, args.loss)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.listen_port))
    pc = (args.pc_ip, args.pc_port)
    print(f"{args.nodes} simulated node(s) -> {pc[0]}:{pc[1]}, "
          f"listening on {args.listen_port} (Ctrl+C to stop)")

    now = time.monotonic()
    next_report = now
    next_reboot = now + args.reboot_every if args.reboot_every else None
    try:
        while True:
            now = time.monotonic()
            if now >= next_report:
                for data in sim.telemetry(now):
                    sock.sendto(data, pc)
                next_report += args.interval
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
