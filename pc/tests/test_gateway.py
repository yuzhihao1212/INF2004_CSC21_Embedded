"""Tests for pc/mosaic/gateway.py and pc/mosaic/simulator.py.

Run from the pc/ folder:  python -m unittest -v
"""

import io
import socket
import time
import unittest

from mosaic import protocol as p
from mosaic.gateway import (CONFIG_FAILED_WAIT_S, CONFIG_MAX_SENDS, ConfigState, Gateway,
                            GatewayServer, NodeStatus)
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
        self.assertEqual((node.received, node.lost, node.duplicates), (3, 0, 1))

    def test_retry_repairs_gap_without_rewinding_live_reading(self):
        self.gw.handle(telemetry(seq=10, co2_ppm=600), NODE_ADDR, now=1)
        self.gw.handle(telemetry(seq=12, co2_ppm=800), NODE_ADDR, now=3)
        recovered = self.gw.handle(telemetry(seq=11, co2_ppm=700), NODE_ADDR, now=3.1)
        node = self.gw.nodes[1]
        self.assertIsNotNone(recovered)  # Retain recovered history in CSV.
        self.assertEqual((node.received, node.lost, node.recovered), (3, 0, 1))
        self.assertEqual((node.gaps_detected, node.reboots, node.last_seq), (1, 0, 12))
        self.assertEqual(node.telemetry.co2_ppm, 800)

    def test_duplicate_does_not_refresh_reading_or_inflate_delivery(self):
        data = telemetry(seq=10)
        self.gw.handle(data, NODE_ADDR, now=1)
        self.assertIsNone(self.gw.handle(data, NODE_ADDR, now=5))
        node = self.gw.nodes[1]
        self.assertEqual((node.received, node.last_seen), (1, 1))

    def test_retried_boot_packet_after_pong_is_not_a_reboot(self):
        data = telemetry(flags=p.FLAG_FIRST_SINCE_BOOT)
        self.gw.handle(data, NODE_ADDR, now=1)
        self.gw.handle(datagram(p.MsgType.PONG, p.Ping(0), seq=1), NODE_ADDR, now=1.05)
        self.assertIsNone(self.gw.handle(data, NODE_ADDR, now=1.1))
        self.assertEqual((self.gw.nodes[1].reboots, self.gw.nodes[1].duplicates), (0, 1))

    def test_delayed_first_telemetry_after_pong_does_not_reboot(self):
        self.gw.handle(datagram(p.MsgType.PONG, p.Ping(0), seq=1), NODE_ADDR, now=1)
        self.gw.handle(telemetry(flags=p.FLAG_FIRST_SINCE_BOOT), NODE_ADDR, now=1.1)
        self.assertEqual((self.gw.nodes[1].reboots, self.gw.nodes[1].received), (0, 2))

    def test_boot_retry_arrives_after_next_telemetry(self):
        self.gw.handle(telemetry(seq=1, co2_ppm=800), NODE_ADDR, now=1)
        self.gw.handle(telemetry(seq=0, flags=p.FLAG_FIRST_SINCE_BOOT, co2_ppm=600),
                       NODE_ADDR, now=1.1)
        node = self.gw.nodes[1]
        self.assertEqual((node.reboots, node.lost, node.received), (0, 0, 2))
        self.assertEqual(node.telemetry.co2_ppm, 800)

    def test_reordering_across_sequence_wrap(self):
        self.feed(2**32 - 2, 0, 2**32 - 1)
        node = self.gw.nodes[1]
        self.assertEqual((node.lost, node.recovered, node.reboots, node.last_seq), (0, 1, 0, 0))

    def test_gap_tracking_storage_is_bounded(self):
        node = self.feed(0, 10000000)
        self.assertEqual(node.lost, 9999999)
        self.assertLessEqual(len(node._seen), 256)
        self.assertLessEqual(len(node._missing), 255)

    def test_expired_history_does_not_fake_a_reboot(self):
        node = self.feed(700, 1000)
        self.assertIsNone(self.gw.handle(telemetry(seq=701), NODE_ADDR, now=2))
        self.assertEqual((node.last_seq, node.reboots), (1000, 0))

    def test_burst_loss_and_two_retries_deliver_once(self):
        # Lose each fourth original, then each eighth first retry. Deliver
        # the second retry, except one message for which all copies are lost.
        # Repeated copies must not improve the denominator or enter fusion.
        for seq in range(200):
            data = telemetry(seq=seq)
            for attempt, offset in enumerate((0, 0.1, 0.3)):
                lost = seq == 37 or (attempt == 0 and seq % 4 == 0) or (attempt == 1 and seq % 8 == 0)
                if not lost:
                    self.gw.handle(data, NODE_ADDR, now=seq + offset)
        node = self.gw.nodes[1]
        self.assertEqual((node.received, node.lost, node.reboots), (199, 1, 0))
        self.assertAlmostEqual(node.loss_pct, 0.5)
        self.assertGreater(node.duplicates, 0)

    def test_repair_after_intervening_pong(self):
        self.feed(9)
        self.gw.handle(datagram(p.MsgType.PONG, p.Ping(0), seq=11), NODE_ADDR, now=1)
        self.gw.handle(telemetry(seq=10, co2_ppm=700), NODE_ADDR, now=1.1)
        node = self.gw.nodes[1]
        self.assertEqual((node.lost, node.recovered, node.last_seq), (0, 1, 11))
        self.assertEqual(node.telemetry.co2_ppm, 700)

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
        self.assertEqual((header.msg_type, header.node_id), (p.MsgType.PING, 1))  # Destination
        gw.handle(datagram(p.MsgType.PONG, ping, seq=1), NODE_ADDR, now=50.012)
        self.assertAlmostEqual(gw.nodes[1].rtt_ms, 12.0, places=3)

    def test_one_ping_per_node_and_none_to_offline(self):
        gw = Gateway()
        gw.handle(telemetry(node_id=1), ("10.0.0.1", 5006), now=0.0)
        gw.handle(telemetry(node_id=2), ("10.0.0.1", 5006), now=0.0)
        gw.handle(telemetry(node_id=3), ("10.0.0.3", 5006), now=0.0)
        gw.handle(telemetry(node_id=1, seq=1), ("10.0.0.1", 5006), now=20.0)
        gw.handle(telemetry(node_id=2, seq=1), ("10.0.0.1", 5006), now=20.0)
        pings = [(p.decode(data)[0].node_id, addr) for data, addr in gw.pings(now=20.0)]
        self.assertEqual(pings, [(1, ("10.0.0.1", p.PORT_CONFIG)),
                                 (2, ("10.0.0.1", p.PORT_CONFIG))])

    def test_pc_seq_increments(self):
        gw = Gateway()
        gw.handle(telemetry(), NODE_ADDR, now=0.0)
        seqs = [p.decode(gw.pings(now=0.0)[0][0])[0].seq for _ in range(3)]
        self.assertEqual(seqs, [0, 1, 2])


class ConfigDelivery(unittest.TestCase):
    """docs/protocol.md section 5, Configuration delivery."""

    def setUp(self):
        self.gw = Gateway()
        self.node_seq = 0
        self.receive(telemetry())

    def receive(self, data, now=0.0):
        self.gw.handle(data, NODE_ADDR, now)

    def from_node(self, msg_type, payload, flags=0, now=0.0):
        self.node_seq += 1
        self.receive(datagram(msg_type, payload, seq=self.node_seq, flags=flags), now)

    def ack(self, version, status=p.AckStatus.OK, now=0.0):
        self.from_node(p.MsgType.CONFIG_ACK, p.ConfigAck(version, status), now=now)

    def report(self, config_version, now=0.0):
        self.from_node(p.MsgType.TELEMETRY, p.Telemetry(config_version=config_version), now=now)

    def sent(self, now):
        return [p.decode(data) for data, _ in self.gw.config_sends(now)]

    @property
    def delivery(self):
        return self.gw.nodes[1].config

    def test_sends_to_node_and_applies_on_ack(self):
        config = self.gw.set_config(1, now=0.0, report_interval_ms=500)
        self.assertEqual(config.config_version, 1)
        [(header, sent)] = self.sent(0.0)
        self.assertEqual((header.msg_type, header.node_id), (p.MsgType.CONFIG, 1))
        self.assertEqual(sent, config)
        self.assertEqual(self.sent(0.4), [])  # Next retry not due until 0.5 s
        self.ack(1)
        self.assertEqual(self.delivery.state, ConfigState.APPLIED)
        self.assertEqual(self.gw.nodes[1].report_interval_ms, 500)  # Used for STALE timing
        self.assertEqual(self.sent(5.0), [])

    def test_retries_then_fails(self):
        self.gw.set_config(1, now=0.0, mode=p.Mode.QUIET_WORK)
        times = [t / 10 for t in range(0, 40)]  # Poll every 100 ms for 4 s
        sends = [t for t in times if self.sent(t)]
        self.assertEqual(sends, [0.0, 0.5, 1.0, 1.5, 2.0])
        self.assertEqual(len(sends), CONFIG_MAX_SENDS)
        self.assertEqual(self.delivery.state, ConfigState.FAILED)
        self.assertIn("not acknowledged", self.gw.messages[-1])

    def test_lost_ack_but_telemetry_shows_version(self):
        self.gw.set_config(1, now=0.0, mode=p.Mode.DISCUSSION)
        self.sent(0.0)
        self.report(1, now=0.3)
        self.assertEqual(self.delivery.state, ConfigState.APPLIED)
        self.assertEqual(self.sent(0.5), [])

    def test_resends_after_reboot(self):
        self.gw.set_config(1, now=0.0, mode=p.Mode.DISCUSSION)
        self.sent(0.0)
        self.ack(1)
        self.node_seq = -1  # Reboot: seq restarts, config back to defaults
        self.from_node(p.MsgType.TELEMETRY, p.Telemetry(config_version=0),
                       flags=p.FLAG_FIRST_SINCE_BOOT, now=10.0)
        self.assertEqual(self.gw.nodes[1].reboots, 1)
        [(_, sent)] = self.sent(10.0)
        self.assertEqual((sent.config_version, sent.mode), (1, p.Mode.DISCUSSION))

    def test_telemetry_sent_before_ack_does_not_resend(self):
        self.gw.set_config(1, now=0.0, mode=p.Mode.DISCUSSION)
        self.sent(0.0)
        self.ack(1)
        # A TELEMETRY the node sent before applying arrives late (lower seq).
        self.receive(datagram(p.MsgType.TELEMETRY, p.Telemetry(config_version=0), seq=1))
        self.assertEqual(self.delivery.state, ConfigState.APPLIED)
        self.assertEqual(self.sent(1.0), [])

    def test_stale_version_jumps_past_node(self):
        # PC restarted: it counts from 1, but the node already runs version 7.
        self.gw.set_config(1, now=0.0, mode=p.Mode.DISCUSSION)  # No TELEMETRY with 7 yet
        self.sent(0.0)
        self.report(7)
        self.ack(1, p.AckStatus.STALE_VERSION)
        [(_, sent)] = self.sent(0.1)
        self.assertEqual(sent.config_version, 8)
        self.ack(8)
        self.assertEqual(self.delivery.state, ConfigState.APPLIED)

    def test_next_version_above_reported(self):
        self.report(41)
        self.assertEqual(self.gw.set_config(1, now=0.0).config_version, 42)

    def test_rejected_is_not_retried(self):
        self.gw.set_config(1, now=0.0)
        self.sent(0.0)
        self.ack(1, p.AckStatus.INVALID_VALUE)
        self.assertEqual(self.delivery.state, ConfigState.REJECTED)
        self.report(0, now=1.0)
        self.assertEqual(self.sent(1.0), [])

    def test_failed_retries_after_wait(self):
        self.gw.set_config(1, now=0.0)
        for t in range(30):
            self.sent(t / 10)
        self.assertEqual(self.delivery.state, ConfigState.FAILED)
        self.report(0, now=3.0)  # Too soon
        self.assertEqual(self.delivery.state, ConfigState.FAILED)
        self.report(0, now=3.0 + CONFIG_FAILED_WAIT_S)
        self.assertEqual(self.delivery.state, ConfigState.SENDING)

    def test_set_config_keeps_earlier_fields(self):
        self.gw.set_config(1, now=0.0, report_interval_ms=500)
        config = self.gw.set_config(1, now=1.0, mode=p.Mode.QUIET_WORK)
        self.assertEqual((config.config_version, config.report_interval_ms, config.mode),
                         (2, 500, p.Mode.QUIET_WORK))

    def test_set_config_rejects_bad_requests(self):
        with self.assertRaises(KeyError):
            self.gw.set_config(5, now=0.0)
        for fields in [dict(report_interval_ms=1), dict(config_version=3), dict(colour=1)]:
            with self.subTest(**fields), self.assertRaises(ValueError):
                self.gw.set_config(1, now=0.0, **fields)
        self.assertIsNone(self.delivery)


class Simulated(unittest.TestCase):
    def test_simulator_telemetry_decodes(self):
        sim = Simulator(nodes=2, seed=1, aligned=True)
        datagrams = sim.telemetry(now=0.0)
        self.assertEqual(len(datagrams), 2)
        for node_id, data in enumerate(datagrams, start=1):
            header, t = p.decode(data)
            self.assertEqual((header.node_id, header.flags), (node_id, p.FLAG_FIRST_SINCE_BOOT))
            self.assertIn(p.Valid.CO2_WARMUP, t.valid_flags)
            self.assertNotIn(p.Valid.CO2, t.valid_flags)
        header, _ = p.decode(sim.telemetry(now=1.0)[0])
        self.assertEqual((header.seq, header.flags), (1, 0))

    def test_simulator_reports_both_audio_windows(self):
        sim = Simulator(nodes=1, seed=1, aligned=True)
        _, first = p.decode(sim.telemetry(now=0.0)[0])
        _, second = p.decode(sim.telemetry(now=1.0)[0])
        self.assertEqual(len(first.audio), p.AUDIO_WINDOWS_PER_REPORT)
        self.assertEqual(second.audio_window_seq - first.audio_window_seq,
                         p.AUDIO_WINDOWS_PER_REPORT)

    def test_simulated_node_checks_config(self):
        sim = Simulator(nodes=2, seed=1, aligned=True)

        def send(node_id, version):
            data = p.encode(p.Header(p.MsgType.CONFIG, node_id, 0, 0), p.Config(version))
            return [p.decode(r) for r in sim.handle(data, now=0.0)]

        [(header, ack)] = send(2, 5)
        self.assertEqual((header.node_id, ack), (2, p.ConfigAck(5, p.AckStatus.OK)))
        self.assertEqual(sim.nodes[0].config_version, 0)  # Node 1 ignored it
        [(_, ack)] = send(2, 4)
        self.assertEqual(ack, p.ConfigAck(4, p.AckStatus.STALE_VERSION))
        self.assertEqual(sim.nodes[1].config_version, 5)
        self.assertEqual(send(0, 6), [])  # No node 0

    def test_simulator_loss_consumes_seq(self):
        sim = Simulator(nodes=1, seed=1, loss=1.0, aligned=True)
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

        sim = Simulator(nodes=3, seed=2, aligned=True)
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

        # One PING per node; each simulated node answers its own, all get an RTT.
        server.send_pings()
        for _ in range(3):
            data, source = node_sock.recvfrom(p.MAX_DATAGRAM)
            replies = sim.handle(data, now=5.0)
            self.assertEqual(len(replies), 1)
            node_sock.sendto(replies[0], source)
        self._poll_until(server, lambda: all(n.rtt_ms is not None
                                             for n in server.gateway.nodes.values()))

        # CONFIG to node 2 only: delivered, acknowledged and applied.
        server.set_config(2, report_interval_ms=500)
        server.poll(timeout=0)
        data, source = node_sock.recvfrom(p.MAX_DATAGRAM)
        [reply] = sim.handle(data, now=6.0)
        node_sock.sendto(reply, source)
        self._poll_until(server, lambda: server.gateway.nodes[2].config.state
                         == ConfigState.APPLIED)
        self.assertEqual([n.config_version for n in sim.nodes], [0, 1, 0])
        self.assertIn("node 2: CONFIG 1 applied", server.out.getvalue())

    def _poll_until(self, server, condition):
        deadline = time.monotonic() + 2.0
        while not condition():
            self.assertLess(time.monotonic(), deadline, "gateway did not receive in time")
            server.poll(timeout=0.05)


if __name__ == "__main__":
    unittest.main()
