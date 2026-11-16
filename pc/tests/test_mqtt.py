"""MQTT client, transport and gateway over MQTT (no Mosquitto needed: tests use
the small broker in mqtt_broker.py)."""

import io
import json
import select
import time
import unittest

from mosaic import mqtt as m
from mosaic import protocol as p
from mosaic.gateway import ConfigState, GatewayServer
from mosaic.simulator import MqttLink, Simulator
from tests.mqtt_broker import TestBroker, topic_matches


def wait_for(condition, timeout=3.0, step=None):
    """Run step() until condition() holds; fail after timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if step:
            step()
        if condition():
            return True
        time.sleep(0.01)
    raise AssertionError("timed out")


def read_until(client, condition, timeout=3.0):
    got = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not condition(got):
        if select.select([client], [], [], 0.05)[0]:
            got += client.read()
    return got


class Codec(unittest.TestCase):
    def test_remaining_length(self):
        cases = {0: b"\x00", 127: b"\x7f", 128: b"\x80\x01", 16383: b"\xff\x7f",
                 16384: b"\x80\x80\x01", 268_435_455: b"\xff\xff\xff\x7f"}
        for n, encoded in cases.items():
            self.assertEqual(m.encode_length(n), encoded)
            buf = bytearray(bytes([0xC0]) + encoded + b"x" * n) if n < 20000 else None
            if buf is not None:
                [(kind, _, body)] = m.split_packets(buf)
                self.assertEqual((kind, len(body), len(buf)), (12, n, 0))
        with self.assertRaises(ValueError):
            m.encode_length(268_435_456)

    def test_connect_bytes_follow_the_spec(self):
        # MQTT 3.1.1 section 3.1: protocol name, level 4, clean session, keep-alive 30
        self.assertEqual(m.connect_packet("mosaic", 30),
                         bytes.fromhex("1012" "00044d515454" "04" "02" "001e" "0006") + b"mosaic")
        will = m.connect_packet("n1", 30, ("t", b"off", 1, True))
        self.assertEqual(will[9], 0x02 | 0x04 | 0x08 | 0x20)  # will flag, QoS 1, retain

    def test_publish_round_trip_and_partial_reads(self):
        data = m.publish_packet("mosaic/node/3/config", b"\x01\x02", qos=1, retain=True, packet_id=7)
        buf = bytearray()
        for byte in data[:-1]:          # Arriving one byte at a time: nothing complete yet
            buf.append(byte)
            self.assertEqual(m.split_packets(buf), [])
        buf.append(data[-1])
        [(kind, flags, body)] = m.split_packets(buf)
        message, packet_id = m.parse_publish(flags, body)
        self.assertEqual((kind, message.topic, message.payload, message.retain, message.qos, packet_id),
                         (m.PUBLISH, "mosaic/node/3/config", b"\x01\x02", True, 1, 7))

    def test_topics(self):
        self.assertEqual(m.topic_node("mosaic/node/3/telemetry", "telemetry"), 3)
        for bad in ("mosaic/node/3/config", "mosaic/node/03/telemetry", "mosaic/node/0/telemetry",
                    "mosaic/node/9/telemetry", "mosaic/node/x/telemetry", "other/node/3/telemetry",
                    "mosaic/node/3/telemetry/extra"):
            self.assertIsNone(m.topic_node(bad, "telemetry"), bad)
        self.assertEqual(m.parse_broker("localhost"), ("localhost", 1883))
        self.assertEqual(m.parse_broker("10.0.0.2:1884"), ("10.0.0.2", 1884))
        self.assertTrue(topic_matches("mosaic/node/+/telemetry", "mosaic/node/4/telemetry"))
        self.assertFalse(topic_matches("mosaic/node/+/telemetry", "mosaic/node/4/config"))


class ClientWithBroker(unittest.TestCase):
    def setUp(self):
        self.broker = TestBroker()
        self.addCleanup(self.broker.close)

    def client(self, name, **kw):
        c = m.MqttClient("127.0.0.1", self.broker.port, client_id=name, **kw)
        c.connect()
        self.addCleanup(c.close)
        return c

    def test_qos1_is_acknowledged_and_retained_messages_reach_late_subscribers(self):
        a = self.client("a")
        a.publish("mosaic/node/2/config", b"cfg", qos=1, retain=True)
        self.assertEqual(a.unacknowledged, 1)
        read_until(a, lambda _: a.unacknowledged == 0)
        self.assertEqual(a.unacknowledged, 0)
        b = self.client("b")
        b.subscribe("mosaic/node/2/config", qos=1)
        got = read_until(b, lambda g: g)
        self.assertEqual([(x.topic, x.payload, x.retain) for x in got],
                         [("mosaic/node/2/config", b"cfg", True)])

    def test_last_will_on_abrupt_loss_but_not_on_disconnect(self):
        watcher = self.client("watcher")
        watcher.subscribe("mosaic/node/+/status", qos=1)
        node = self.client("node1", will=(m.status_topic(1), b"offline", 1, True))
        node.sock.close()  # Power cut: no DISCONNECT
        node.sock = None
        got = read_until(watcher, lambda g: g)
        self.assertEqual((got[0].topic, got[0].payload), ("mosaic/node/1/status", b"offline"))
        polite = self.client("node2", will=(m.status_topic(2), b"offline", 1, True))
        polite.close()
        time.sleep(0.2)
        self.assertNotIn(("mosaic/node/2/status", b"offline", 1, True), self.broker.published)

    def test_keepalive_pings_and_unacknowledged_resend(self):
        c = self.client("k", keepalive=2)
        c.tick(time.monotonic() + 1.1)
        wait_for(lambda: self.broker.pings == 1)
        c.publish("t", b"x", qos=1)
        c._inflight[next(iter(c._inflight))].sent -= m.RESEND_S  # PUBACK "lost"
        c.tick()
        wait_for(lambda: len([x for x in self.broker.published if x[0] == "t"]) == 2)

    def test_silent_broker_is_detected(self):
        self.broker.mute_pings = True
        c = self.client("quiet", keepalive=2)
        with self.assertRaises(ConnectionError):
            c.tick(time.monotonic() + 3.1)
        self.assertFalse(c.connected)

    def test_refused_connection(self):
        self.broker.connack_code = 5
        c = m.MqttClient("127.0.0.1", self.broker.port, client_id="x")
        with self.assertRaisesRegex(m.MqttError, "not authorised"):
            c.connect()


class GatewayOverMqtt(unittest.TestCase):
    """A fake node on its own MQTT client, and the real GatewayServer."""

    def setUp(self):
        self.broker = TestBroker()
        self.addCleanup(self.broker.close)
        self.events = io.StringIO()
        self.server = GatewayServer(out=io.StringIO(), events_file=self.events,
                                    transport=m.MqttTransport("127.0.0.1", self.broker.port))
        self.addCleanup(self.server.close)
        self.node = m.MqttClient("127.0.0.1", self.broker.port, client_id="node3",
                                 will=(m.status_topic(3), b"offline", 1, True))
        self.node.connect()
        self.node.subscribe(m.config_topic(3), qos=1)
        self.addCleanup(self.node.close)
        self.seq = 0

    def send(self, payload, msg_type=p.MsgType.TELEMETRY, node_id=3, topic_node=3):
        header = p.Header(msg_type, node_id, self.seq, int(time.monotonic() * 1000) % (1 << 32))
        self.seq += 1
        self.node.publish(m.telemetry_topic(topic_node), p.encode(header, payload))

    def node_inbox(self, condition):
        return read_until(self.node, condition)

    def test_telemetry_config_ack_and_ping(self):
        self.send(p.Telemetry(co2_ppm=650))
        wait_for(lambda: 3 in self.server.gateway.nodes, step=lambda: self.server.poll(0.05))
        self.assertEqual(self.server.gateway.nodes[3].telemetry.co2_ppm, 650)

        cfg = self.server.set_config(3, report_interval_ms=2000)
        self.server.poll(0.05)  # Sends the CONFIG
        got = self.node_inbox(lambda g: any(x.qos == 1 for x in g))
        message = next(x for x in got if x.qos == 1)
        header, config = p.decode(message.payload)
        self.assertEqual((message.topic, header.msg_type, config.config_version),
                         (m.config_topic(3), p.MsgType.CONFIG, cfg.config_version))
        self.assertTrue(("mosaic/node/3/config", message.payload, 1, True) in self.broker.published)

        self.send(p.ConfigAck(cfg.config_version, p.AckStatus.OK), p.MsgType.CONFIG_ACK)
        wait_for(lambda: self.server.gateway.nodes[3].config.state == ConfigState.APPLIED,
                 step=lambda: self.server.poll(0.05))

        self.server.send_pings()
        got = self.node_inbox(lambda g: any(p.decode(x.payload)[0].msg_type == p.MsgType.PING for x in g))
        ping = next(x for x in got if p.decode(x.payload)[0].msg_type == p.MsgType.PING)
        self.assertFalse(ping.retain)  # PINGs are not left on the broker
        self.send(p.decode(ping.payload)[1], p.MsgType.PONG)
        wait_for(lambda: self.server.gateway.nodes[3].rtt_ms is not None,
                 step=lambda: self.server.poll(0.05))
        self.assertGreaterEqual(self.server.gateway.nodes[3].rtt_ms, 0)

    def test_node_may_not_speak_for_another(self):
        self.send(p.Telemetry(), node_id=4, topic_node=3)
        self.send(p.Telemetry(), node_id=3, topic_node=3)
        wait_for(lambda: 3 in self.server.gateway.nodes, step=lambda: self.server.poll(0.05))
        self.assertNotIn(4, self.server.gateway.nodes)
        self.assertEqual(self.server.transport.dropped, 1)

    def test_last_will_is_logged(self):
        self.node.sock.close()  # Power cut
        self.node.sock = None
        wait_for(lambda: '"event":"link"' in self.events.getvalue(), step=lambda: self.server.poll(0.05))
        link = [json.loads(line) for line in self.events.getvalue().splitlines()
                if '"event":"link"' in line]
        self.assertEqual((link[-1]["node"], link[-1]["state"]), (3, "offline"))

    def test_gateway_reconnects_after_the_broker_restarts(self):
        port = self.broker.port
        self.broker.close()
        wait_for(lambda: not self.server.transport.client.connected, step=lambda: self.server.poll(0.05))
        self.broker = TestBroker(port)
        self.addCleanup(self.broker.close)
        self.server.transport._retry_at = 0
        wait_for(lambda: self.server.transport.client.connected, step=lambda: self.server.poll(0.05))
        node = m.MqttClient("127.0.0.1", port, client_id="node5")
        node.connect()
        self.addCleanup(node.close)
        node.publish(m.telemetry_topic(5), p.encode(p.Header(p.MsgType.TELEMETRY, 5, 0, 0), p.Telemetry()))
        wait_for(lambda: 5 in self.server.gateway.nodes, step=lambda: self.server.poll(0.05))


class SimulatedNodesOverMqtt(unittest.TestCase):
    def test_simulated_nodes_reach_the_gateway_and_answer_config(self):
        broker = TestBroker()
        self.addCleanup(broker.close)
        server = GatewayServer(out=io.StringIO(), transport=m.MqttTransport("127.0.0.1", broker.port))
        self.addCleanup(server.close)
        sim = Simulator(2, seed=1, aligned=True, report_interval_s=0.2)
        link = MqttLink("127.0.0.1", broker.port, [n.node_id for n in sim.nodes])
        self.addCleanup(link.close)

        def step():
            now = time.monotonic()
            for _, data in sim.poll(now):
                link.send(data)
            for data, reply in link.wait(0.02):
                for answer in sim.handle(data, time.monotonic()):
                    reply(answer)
            server.poll(0.02)

        wait_for(lambda: set(server.gateway.nodes) == {1, 2}, step=step)
        server.set_config(2, report_interval_ms=500)
        wait_for(lambda: server.gateway.nodes[2].config.state == ConfigState.APPLIED, step=step)
        self.assertIn(("mosaic/node/1/status", b"online", 1, True), broker.published)


if __name__ == "__main__":
    unittest.main()
