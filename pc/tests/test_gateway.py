"""Tests for pc/mosaic/gateway.py and pc/mosaic/simulator.py.

Run from the pc/ folder:  python -m unittest -v
"""

import io
import socket
import time
import unittest

from mosaic import protocol as p
from mosaic.gateway import Gateway, GatewayServer, NodeStatus
from mosaic.simulator import Simulator

NODE_ADDR = ("192.168.1.21", p.PORT_CONFIG)


def datagram(msg_type, payload, node_id=1, seq=0, flags=0):
    return p.encode(p.Header(msg_type, node_id, seq, sender_time_ms=seq * 1000 % 2**32, flags=flags),
                    payload)


def telemetry(node_id=1, seq=0, flags=0, **fields):
    return datagram(p.MsgType.TELEMETRY, p.Telemetry(**fields), node_id, seq, flags)


class Receiving(unittest.TestCase):
    def setUp(self):
        self.gw = Gateway()

    def test_telemetry_registers_node(self):
        result = self.gw.handle(telemetry(seq=5, co2_ppm=650), NODE_ADDR, now=1.0)
        self.assertIsNotNone(result)
        node = self.gw.nodes[1]
        self.assertEqual(node.address, NODE_ADDR)
        self.assertEqual(node.telemetry.co2_ppm, 650)
        self.assertEqual((node.received, node.lost), (1, 0))

    def test_config_ack_recorded(self):
        self.gw.handle(datagram(p.MsgType.CONFIG_ACK, p.ConfigAck(4, p.AckStatus.INVALID_VALUE)),
                       NODE_ADDR, now=1.0)
        self.assertEqual(self.gw.nodes[1].last_ack, p.ConfigAck(4, p.AckStatus.INVALID_VALUE))

    def test_malformed_dropped_per_source(self):
        self.assertIsNone(self.gw.handle(b"not a mosaic packet", NODE_ADDR, now=1.0))
        self.assertIsNone(self.gw.handle(telemetry()[:-1], NODE_ADDR, now=1.0))
        self.assertEqual(self.gw.dropped[NODE_ADDR[0]], 2)
        self.assertEqual(self.gw.nodes, {})

    def test_pc_messages_and_bad_node_ids_dropped(self):
        cases = [
            datagram(p.MsgType.PING, p.Ping(1)),            # PC -> node type
            datagram(p.MsgType.CONFIG, p.Config(1)),        # PC -> node type
            telemetry(node_id=0),                           # 0 is the PC
            telemetry(node_id=p.MAX_NODES + 1),
        ]
        for data in cases:
            self.assertIsNone(self.gw.handle(data, NODE_ADDR, now=1.0))
        self.assertEqual(self.gw.dropped[NODE_ADDR[0]], len(cases))
        self.assertEqual(self.gw.nodes, {})


class SequenceTracking(unittest.TestCase):
    def setUp(self):
        self.gw = Gateway()

    def feed(self, *seqs, flags=0):
        for seq in seqs:
            self.gw.handle(telemetry(seq=seq, flags=flags), NODE_ADDR, now=1.0)
        return self.gw.nodes[1]

    def test_gap_counts_loss(self):
        node = self.feed(10, 11, 14, 15)
        self.assertEqual((node.received, node.lost), (4, 2))
        self.assertAlmostEqual(node.loss_pct, 100 * 2 / 6)

    def test_duplicate_not_loss(self):
        node = self.feed(10, 11, 11, 12)
        self.assertEqual((node.received, node.lost, node.duplicates), (4, 0, 1))

    def test_backwards_seq_is_reboot(self):
        node = self.feed(500, 501, 0, 1)
        self.assertEqual((node.lost, node.reboots), (0, 1))

    def test_first_since_boot_flag_is_reboot(self):
        # Old boot ended at seq 1; new boot's seq 0..2 lost, so seq doesn't go backwards.
        node = self.feed(0, 1)
        self.gw.handle(telemetry(seq=3, flags=p.FLAG_FIRST_SINCE_BOOT), NODE_ADDR, now=1.0)
        self.assertEqual((node.lost, node.reboots), (3, 1))

    def test_loss_right_after_reboot_counted(self):
        self.feed(500, 501)
        node = self.feed(2, flags=p.FLAG_FIRST_SINCE_BOOT)  # seq 0 and 1 never arrived
        self.assertEqual((node.lost, node.reboots), (2, 1))

    def test_pong_before_flagged_telemetry_is_one_reboot(self):
        self.feed(500)
        self.gw.handle(datagram(p.MsgType.PONG, p.Ping(0), seq=0), NODE_ADDR, now=1.0)
        node = self.feed(1, flags=p.FLAG_FIRST_SINCE_BOOT)
        self.assertEqual((node.lost, node.reboots), (0, 1))

    def test_first_packet_with_flag_is_not_reboot(self):
        node = self.feed(0, flags=p.FLAG_FIRST_SINCE_BOOT)
        self.assertEqual(node.reboots, 0)

    def test_seq_wraps(self):
        node = self.feed(2**32 - 2, 2**32 - 1, 0, 1)
        self.assertEqual((node.lost, node.reboots), (0, 0))

    def test_seq_shared_across_message_types(self):
        self.feed(7)
        self.gw.handle(datagram(p.MsgType.PONG, p.Ping(0), seq=8), NODE_ADDR, now=1.0)
        node = self.feed(9)
        self.assertEqual(node.lost, 0)


class Liveness(unittest.TestCase):
    def test_online_stale_offline(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=100.0)
        node = gw.nodes[1]
        self.assertEqual(node.status(100.0 + 2.9), NodeStatus.ONLINE)
        self.assertEqual(node.status(100.0 + 3.1), NodeStatus.STALE)    # 3 x 1000 ms
        self.assertEqual(node.status(100.0 + 10.1), NodeStatus.OFFLINE)

    def test_stale_follows_report_interval(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=100.0)
        gw.nodes[1].report_interval_ms = 200
        self.assertEqual(gw.nodes[1].status(100.0 + 0.7), NodeStatus.STALE)

    def test_status_changes_reported_once(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=100.0)
        self.assertEqual(gw.status_changes(101.0), [])
        self.assertEqual(gw.status_changes(104.0), [(1, NodeStatus.STALE)])
        self.assertEqual(gw.status_changes(105.0), [])
        self.assertEqual(gw.status_changes(111.0), [(1, NodeStatus.OFFLINE)])
        gw.handle(telemetry(seq=1), NODE_ADDR, now=112.0)
        self.assertEqual(gw.status_changes(112.0), [(1, NodeStatus.ONLINE)])


class Latency(unittest.TestCase):
    def test_pong_gives_rtt(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=50.0)
        pings = gw.pings(now=50.0)
        self.assertEqual(len(pings), 1)
        data, address = pings[0]
        self.assertEqual(address, (NODE_ADDR[0], p.PORT_CONFIG))
        header, ping = p.decode(data)
        self.assertEqual((header.msg_type, header.node_id), (p.MsgType.PING, 0))
        gw.handle(datagram(p.MsgType.PONG, ping, seq=1), NODE_ADDR, now=50.012)
        self.assertAlmostEqual(gw.nodes[1].rtt_ms, 12.0, places=3)

    def test_one_ping_per_address_and_none_to_offline(self):
        gw = Gateway()
        gw.handle(telemetry(node_id=1), ("10.0.0.1", 5006), now=0.0)
        gw.handle(telemetry(node_id=2), ("10.0.0.1", 5006), now=0.0)
        gw.handle(telemetry(node_id=3), ("10.0.0.3", 5006), now=0.0)
        gw.handle(telemetry(node_id=1, seq=1), ("10.0.0.1", 5006), now=20.0)
        self.assertEqual([addr for _, addr in gw.pings(now=20.0)], [("10.0.0.1", p.PORT_CONFIG)])

    def test_pc_seq_increments(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=0.0)
        seqs = [p.decode(gw.pings(now=0.0)[0][0])[0].seq for _ in range(3)]
        self.assertEqual(seqs, [0, 1, 2])


class Simulated(unittest.TestCase):
    def test_simulator_telemetry_decodes(self):
        sim = Simulator(nodes=2, seed=1)
        datagrams = sim.telemetry(now=0.0)
        self.assertEqual(len(datagrams), 2)
        for node_id, data in enumerate(datagrams, start=1):
            header, t = p.decode(data)
            self.assertEqual((header.node_id, header.flags), (node_id, p.FLAG_FIRST_SINCE_BOOT))
            self.assertIn(p.Valid.CO2_WARMUP, t.valid_flags)
            self.assertNotIn(p.Valid.CO2, t.valid_flags)
        header, _ = p.decode(sim.telemetry(now=1.0)[0])
        self.assertEqual((header.seq, header.flags), (1, 0))

    def test_simulator_loss_consumes_seq(self):
        sim = Simulator(nodes=1, seed=1, loss=1.0)
        self.assertEqual(sim.telemetry(now=0.0), [])
        sim.loss = 0.0
        header, _ = p.decode(sim.telemetry(now=1.0)[0])
        self.assertEqual(header.seq, 1)

    def test_end_to_end_over_udp(self):
        server = GatewayServer(bind=("127.0.0.1", 0), config_port=0, out=io.StringIO())
        self.addCleanup(server.close)
        node_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        node_sock.bind(("127.0.0.1", 0))
        node_sock.settimeout(2.0)
        self.addCleanup(node_sock.close)
        server.config_port = node_sock.getsockname()[1]
        gateway_addr = server.sock.getsockname()

        sim = Simulator(nodes=3, seed=2)
        for step in range(4):
            for data in sim.telemetry(now=float(step)):
                node_sock.sendto(data, gateway_addr)
        node_sock.sendto(b"garbage", gateway_addr)
        self._poll_until(server, lambda: server.gateway.dropped["127.0.0.1"] == 1)

        self.assertEqual(sorted(server.gateway.nodes), [1, 2, 3])
        for node in server.gateway.nodes.values():
            self.assertEqual((node.received, node.lost, node.reboots), (4, 0, 0))
        self.assertEqual(server.gateway.dropped["127.0.0.1"], 1)
        self.assertIn("node 2", server.out.getvalue())

        # PING reaches the simulated node, every node answers, all get an RTT.
        server.send_pings()
        data, source = node_sock.recvfrom(p.MAX_DATAGRAM)
        for reply in sim.handle(data, now=5.0):
            node_sock.sendto(reply, source)
        self._poll_until(server, lambda: all(n.rtt_ms is not None
                                             for n in server.gateway.nodes.values()))

    def _poll_until(self, server, condition):
        deadline = time.monotonic() + 2.0
        while not condition():
            self.assertLess(time.monotonic(), deadline, "gateway did not receive in time")
            server.poll(timeout=0.05)


if __name__ == "__main__":
    unittest.main()
