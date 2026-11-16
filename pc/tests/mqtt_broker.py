"""A minimal MQTT 3.1.1 broker for tests, so they need no Mosquitto.

Just enough for MOSAIC's use: CONNECT with a last will, SUBSCRIBE with + and
# wildcards, PUBLISH at QoS 0/1, retained messages, PINGREQ and DISCONNECT.
Delivery uses the lower of the publish and subscription QoS. Not for real use.
"""

import socket
import socketserver
import threading

from mosaic import mqtt as m


def topic_matches(topic_filter: str, topic: str) -> bool:
    f, t = topic_filter.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        broker = self.server.broker
        sock = self.request
        buffer = bytearray()
        will = None
        polite = False
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                for kind, flags, body in m.split_packets(buffer):
                    if kind == m.CONNECT:
                        will = self._parse_connect(body)
                        broker.connections.append(self)
                        self._send(bytes([m.CONNACK << 4, 2, 0, broker.connack_code]))
                        if broker.connack_code:
                            return
                    elif kind == m.SUBSCRIBE:
                        packet_id = body[:2]
                        n = int.from_bytes(body[2:4], "big")
                        topic_filter = body[4:4 + n].decode()
                        qos = body[4 + n]
                        with broker.lock:
                            broker.subs.append((self, topic_filter, min(qos, 1)))
                            retained = [(t, pl, q) for t, (pl, q) in broker.retained.items()
                                        if topic_matches(topic_filter, t)]
                        self._send(bytes([m.SUBACK << 4, 3]) + packet_id + bytes([min(qos, 1)]))
                        for t, pl, q in retained:
                            self.deliver(t, pl, min(q, qos), retain=True)
                    elif kind == m.PUBLISH:
                        message, packet_id = m.parse_publish(flags, body)
                        if message.qos == 1:
                            self._send(bytes([m.PUBACK << 4, 2]) + packet_id.to_bytes(2, "big"))
                        broker.route(message.topic, message.payload, message.qos, message.retain)
                    elif kind == m.PINGREQ:
                        broker.pings += 1
                        if not broker.mute_pings:
                            self._send(bytes([m.PINGRESP << 4, 0]))
                    elif kind == m.DISCONNECT:
                        polite = True
                        return
        except OSError:
            pass
        finally:
            with broker.lock:
                broker.subs = [s for s in broker.subs if s[0] is not self]
                if self in broker.connections:
                    broker.connections.remove(self)
            if will and not polite:
                broker.route(*will)

    def _parse_connect(self, body):
        n = int.from_bytes(body[0:2], "big")
        i = 2 + n + 1  # Protocol name, level
        flags = body[i]
        i += 1 + 2      # Flags, keep-alive
        n = int.from_bytes(body[i:i + 2], "big")
        self.client_id = body[i + 2:i + 2 + n].decode()
        i += 2 + n
        if not flags & 0x04:
            return None
        n = int.from_bytes(body[i:i + 2], "big")
        topic = body[i + 2:i + 2 + n].decode()
        i += 2 + n
        n = int.from_bytes(body[i:i + 2], "big")
        payload = bytes(body[i + 2:i + 2 + n])
        return topic, payload, (flags >> 3) & 0x03, bool(flags & 0x20)

    def _send(self, data):
        with self.server.broker.lock:
            self.request.sendall(data)

    def deliver(self, topic, payload, qos, retain=False):
        packet_id = self.server.broker.next_id() if qos else 0
        try:
            self._send(m.publish_packet(topic, payload, qos, retain, packet_id))
        except OSError:
            pass

    def drop(self):
        """Cut the connection without DISCONNECT, as a crash or Wi-Fi loss would."""
        try:
            self.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class TestBroker:
    def __init__(self, port: int = 0):
        self.lock = threading.RLock()
        self.subs = []          # (handler, filter, qos)
        self.retained = {}      # topic -> (payload, qos)
        self.published = []    # every routed (topic, payload, qos, retain)
        self.connections = []
        self.connack_code = 0
        self.mute_pings = False
        self.pings = 0
        self._id = 0
        self.server = _Server(("127.0.0.1", port), _Handler)
        self.server.broker = self
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def next_id(self):
        with self.lock:
            self._id = self._id % 0xFFFF + 1
            return self._id

    def route(self, topic, payload, qos, retain):
        with self.lock:
            self.published.append((topic, payload, qos, retain))
            if retain:
                if payload:
                    self.retained[topic] = (payload, qos)
                else:
                    self.retained.pop(topic, None)
            targets = [(h, q) for h, f, q in self.subs if topic_matches(f, topic)]
        for handler, sub_qos in targets:
            handler.deliver(topic, payload, min(qos, sub_qos))

    def drop_all(self):
        for handler in list(self.connections):
            handler.drop()

    def close(self):
        self.drop_all()
        self.server.shutdown()
        self.server.server_close()
