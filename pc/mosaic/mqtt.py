"""A small MQTT 3.1.1 client, standard library only, and MOSAIC's MQTT transport.

The node talks to the PC through an MQTT broker (Mosquitto on the demo laptop;
docs/decision-log.md, 16 Nov). Each message carries one protocol v2 packet,
unchanged (docs/protocol.md), on these topics:

    mosaic/node/<id>/telemetry  node -> PC: every packet the node sends
                                (TELEMETRY, PONG, CONFIG_ACK); QoS 0
    mosaic/node/<id>/config     PC -> node: CONFIG (QoS 1, retained, so a node
                                that reconnects gets its config back) and PING
                                (QoS 0, not retained)
    mosaic/node/<id>/status     the node's last will: "offline" (retained) when
                                its connection drops, "online" when it connects

Only what the gateway and the simulated nodes need is implemented: a clean
session, CONNECT with a last will, SUBSCRIBE, PUBLISH at QoS 0 and 1 (QoS 1
resent until PUBACK), and keep-alive. No QoS 2, no TLS, no username/password.
"""

from __future__ import annotations

import select
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

from mosaic import protocol as p

DEFAULT_PORT = 1883
KEEPALIVE_S = 30
RESEND_S = 5.0          # Resend an unacknowledged QoS 1 PUBLISH this often
RECONNECT_S = 2.0       # Wait before reconnecting after the broker goes away

TOPIC_ROOT = "mosaic/node"

# Packet types (high nibble of the first byte)
CONNECT, CONNACK, PUBLISH, PUBACK = 1, 2, 3, 4
SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 8, 9, 12, 13, 14

_CONNACK_ERRORS = {1: "unacceptable protocol version", 2: "client ID rejected",
                   3: "server unavailable", 4: "bad user name or password",
                   5: "not authorised"}


class MqttError(Exception):
    pass


# ---------------------------------------------------------------- topics


def telemetry_topic(node_id: int) -> str:
    return f"{TOPIC_ROOT}/{node_id}/telemetry"


def config_topic(node_id: int) -> str:
    return f"{TOPIC_ROOT}/{node_id}/config"


def status_topic(node_id: int) -> str:
    return f"{TOPIC_ROOT}/{node_id}/status"


def topic_node(topic: str, kind: str) -> Optional[int]:
    """The node ID in mosaic/node/<id>/<kind>, or None if the topic doesn't match."""
    parts = topic.split("/")
    if len(parts) != 4 or "/".join(parts[:2]) != TOPIC_ROOT or parts[3] != kind:
        return None
    try:
        node_id = int(parts[2])
    except ValueError:
        return None
    return node_id if 1 <= node_id <= p.MAX_NODES and parts[2] == str(node_id) else None


def parse_broker(text: str) -> tuple[str, int]:
    """'host' or 'host:port' -> (host, port)."""
    host, _, port = text.rpartition(":") if ":" in text else (text, "", "")
    if not host:
        raise ValueError(f"broker address {text!r}: expected HOST or HOST:PORT")
    return host, int(port) if port else DEFAULT_PORT


# ---------------------------------------------------------------- packets


def encode_length(n: int) -> bytes:
    """MQTT 'remaining length': 7 bits per byte, low bits first."""
    if not 0 <= n <= 268_435_455:
        raise ValueError("MQTT packet too long")
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _string(text: str) -> bytes:
    data = text.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def _blob(data: bytes) -> bytes:
    return len(data).to_bytes(2, "big") + data


def _packet(first: int, body: bytes) -> bytes:
    return bytes([first]) + encode_length(len(body)) + body


def connect_packet(client_id: str, keepalive: int,
                   will: Optional[tuple[str, bytes, int, bool]] = None) -> bytes:
    flags = 0x02  # Clean session
    payload = _string(client_id)
    if will:
        topic, message, qos, retain = will
        flags |= 0x04 | (qos << 3) | (0x20 if retain else 0)
        payload += _string(topic) + _blob(message)
    body = _string("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big") + payload
    return _packet(CONNECT << 4, body)


def publish_packet(topic: str, payload: bytes, qos: int = 0, retain: bool = False,
                   packet_id: int = 0, dup: bool = False) -> bytes:
    first = (PUBLISH << 4) | (0x08 if dup else 0) | (qos << 1) | (0x01 if retain else 0)
    body = _string(topic) + (packet_id.to_bytes(2, "big") if qos else b"") + payload
    return _packet(first, body)


def subscribe_packet(packet_id: int, topic_filter: str, qos: int) -> bytes:
    return _packet((SUBSCRIBE << 4) | 0x02,
                   packet_id.to_bytes(2, "big") + _string(topic_filter) + bytes([qos]))


def split_packets(buffer: bytearray) -> list[tuple[int, int, bytes]]:
    """Take every complete packet off the front of buffer: (type, flags, body)."""
    packets = []
    while len(buffer) >= 2:
        length, multiplier, i = 0, 1, 1
        while True:
            if i >= len(buffer):
                return packets  # Length bytes not all here yet
            byte = buffer[i]
            length += (byte & 0x7F) * multiplier
            multiplier *= 128
            i += 1
            if not byte & 0x80:
                break
            if i > 4:
                raise MqttError("malformed remaining length")
        if len(buffer) < i + length:
            return packets
        first = buffer[0]
        packets.append((first >> 4, first & 0x0F, bytes(buffer[i:i + length])))
        del buffer[:i + length]
    return packets


@dataclass
class Message:
    topic: str
    payload: bytes
    retain: bool = False
    qos: int = 0


def parse_publish(flags: int, body: bytes) -> tuple[Message, int]:
    """(message, packet ID); the ID is 0 for QoS 0."""
    qos = (flags >> 1) & 0x03
    n = int.from_bytes(body[:2], "big")
    topic = body[2:2 + n].decode("utf-8")
    i = 2 + n
    packet_id = 0
    if qos:
        packet_id = int.from_bytes(body[i:i + 2], "big")
        i += 2
    return Message(topic, body[i:], bool(flags & 0x01), qos), packet_id


# ---------------------------------------------------------------- client


@dataclass
class _InFlight:
    topic: str
    payload: bytes
    retain: bool
    sent: float


class MqttClient:
    """One connection to the broker. Call read() when fileno() is readable
    and tick() every so often; both raise ConnectionError if the link drops."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, client_id: str = "mosaic",
                 keepalive: int = KEEPALIVE_S,
                 will: Optional[tuple[str, bytes, int, bool]] = None) -> None:
        self.host, self.port = host, port
        self.client_id = client_id
        self.keepalive = keepalive
        self.will = will
        self.sock: Optional[socket.socket] = None
        self._buffer = bytearray()
        self._next_id = 0
        self._inflight: dict[int, _InFlight] = {}
        self._last_out = self._last_in = 0.0
        self.subscribe_failures: list[str] = []
        self._pending_subs: dict[int, str] = {}

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def fileno(self) -> int:
        return self.sock.fileno() if self.sock else -1

    def connect(self, timeout: float = 5.0) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        try:
            sock.sendall(connect_packet(self.client_id, self.keepalive, self.will))
            deadline = time.monotonic() + timeout
            buffer = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([sock], [], [], remaining)[0]:
                    raise MqttError("no CONNACK from the broker")
                chunk = sock.recv(4096)
                if not chunk:
                    raise MqttError("broker closed the connection")
                buffer += chunk
                packets = split_packets(buffer)
                if packets:
                    kind, _, body = packets[0]
                    if kind != CONNACK or len(body) != 2:
                        raise MqttError("expected CONNACK")
                    if body[1]:
                        raise MqttError(f"broker refused: {_CONNACK_ERRORS.get(body[1], body[1])}")
                    break
        except BaseException:
            sock.close()
            raise
        self.sock = sock
        self._buffer = buffer
        self._inflight.clear()
        self._last_out = self._last_in = time.monotonic()

    def _send(self, data: bytes) -> None:
        if not self.sock:
            raise ConnectionError("not connected to the MQTT broker")
        try:
            self.sock.sendall(data)
        except OSError as e:
            self._drop()
            raise ConnectionError(f"MQTT send failed: {e}") from e
        self._last_out = time.monotonic()

    def _packet_id(self) -> int:
        self._next_id = self._next_id % 0xFFFF + 1
        return self._next_id

    def subscribe(self, topic_filter: str, qos: int = 0) -> None:
        packet_id = self._packet_id()
        self._pending_subs[packet_id] = topic_filter
        self._send(subscribe_packet(packet_id, topic_filter, qos))

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        if qos not in (0, 1):
            raise ValueError("only QoS 0 and 1 are supported")
        packet_id = self._packet_id() if qos else 0
        self._send(publish_packet(topic, payload, qos, retain, packet_id))
        if qos:
            self._inflight[packet_id] = _InFlight(topic, payload, retain, time.monotonic())

    def read(self) -> list[Message]:
        """Messages that arrived; call when fileno() is readable."""
        if not self.sock:
            raise ConnectionError("not connected to the MQTT broker")
        try:
            chunk = self.sock.recv(65536)
        except (BlockingIOError, socket.timeout):
            return []
        except OSError as e:
            self._drop()
            raise ConnectionError(f"MQTT receive failed: {e}") from e
        if not chunk:
            self._drop()
            raise ConnectionError("the MQTT broker closed the connection")
        self._last_in = time.monotonic()
        self._buffer += chunk
        messages = []
        for kind, flags, body in split_packets(self._buffer):
            if kind == PUBLISH:
                message, packet_id = parse_publish(flags, body)
                if message.qos == 1:
                    self._send(_packet(PUBACK << 4, packet_id.to_bytes(2, "big")))
                messages.append(message)
            elif kind == PUBACK:
                self._inflight.pop(int.from_bytes(body[:2], "big"), None)
            elif kind == SUBACK:
                topic = self._pending_subs.pop(int.from_bytes(body[:2], "big"), "?")
                if 0x80 in body[2:]:
                    self.subscribe_failures.append(topic)
        return messages

    def tick(self, now: Optional[float] = None) -> None:
        """Keep-alive and QoS 1 resends."""
        if not self.sock:
            return
        now = time.monotonic() if now is None else now
        if now - self._last_in > self.keepalive * 1.5:
            self._drop()
            raise ConnectionError("the MQTT broker stopped answering")
        if now - self._last_out >= self.keepalive / 2:
            self._send(bytes([PINGREQ << 4, 0]))
        for packet_id, f in list(self._inflight.items()):
            if now - f.sent >= RESEND_S:
                self._send(publish_packet(f.topic, f.payload, 1, f.retain, packet_id, dup=True))
                f.sent = now

    @property
    def unacknowledged(self) -> int:
        return len(self._inflight)

    def close(self) -> None:
        """Polite disconnect: the broker does not publish the last will."""
        if self.sock:
            try:
                self.sock.sendall(bytes([DISCONNECT << 4, 0]))
            except OSError:
                pass
        self._drop()

    def _drop(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self._buffer.clear()


# ---------------------------------------------------------------- gateway transport


@dataclass
class Incoming:
    """What a transport hands the gateway: a protocol packet from a node, or a
    node's link status ('online'/'offline') from its MQTT last will."""
    kind: str               # "packet" or "status"
    data: bytes = b""
    address: tuple = ("", 0)
    node_id: Optional[int] = None
    status: str = ""


@dataclass
class MqttTransport:
    """The gateway's link to the nodes through an MQTT broker. Reconnects by
    itself if the broker goes away; the gateway's own CONFIG retries cover
    anything sent while it was down."""
    host: str
    port: int = DEFAULT_PORT
    client_id: str = "mosaic-gateway"
    client: MqttClient = field(init=False)
    dropped: int = 0
    notes: list = field(default_factory=list)   # Lines for the console; caller drains
    _retry_at: float = 0.0

    def __post_init__(self) -> None:
        self.client = MqttClient(self.host, self.port, self.client_id)
        self._connect()

    def describe(self) -> str:
        return f"MQTT broker {self.host}:{self.port}"

    def fileno(self) -> int:
        return self.client.fileno()

    def _connect(self) -> None:
        try:
            self.client.connect()
            self.client.subscribe(f"{TOPIC_ROOT}/+/telemetry", qos=0)
            self.client.subscribe(f"{TOPIC_ROOT}/+/status", qos=1)
            self.notes.append(f"connected to {self.describe()}")
        except (OSError, MqttError) as e:
            self.client._drop()
            self._retry_at = time.monotonic() + RECONNECT_S
            self.notes.append(f"cannot reach {self.describe()}: {e}; retrying")

    def receive(self) -> list[Incoming]:
        try:
            messages = self.client.read()
        except ConnectionError as e:
            self._lost(e)
            return []
        out = []
        for m in messages:
            node_id = topic_node(m.topic, "telemetry")
            if node_id is not None:
                try:
                    header, _ = p.decode(m.payload)
                except p.ProtocolError:
                    header = None   # The gateway counts it as a drop
                if header is not None and header.node_id != node_id:
                    # A node may only speak for itself on its own topic.
                    self.dropped += 1
                    self.notes.append(f"dropped a packet for node {header.node_id} "
                                      f"published on {m.topic}")
                    continue
                out.append(Incoming("packet", m.payload, (f"mqtt:{node_id}", 0), node_id))
                continue
            node_id = topic_node(m.topic, "status")
            if node_id is not None:
                out.append(Incoming("status", node_id=node_id,
                                    status=m.payload.decode("utf-8", "replace").strip()))
        return out

    def send(self, data: bytes, address: tuple) -> None:
        """A PC packet for one node, chosen by the node ID in its header."""
        header, _ = p.decode(data)
        is_config = header.msg_type == p.MsgType.CONFIG
        self.client.publish(config_topic(header.node_id), data,
                            qos=1 if is_config else 0, retain=is_config)

    def tick(self, now: float) -> None:
        if not self.client.connected:
            if now >= self._retry_at:
                self._connect()
            return
        try:
            self.client.tick(now)
        except ConnectionError as e:
            self._lost(e)

    def _lost(self, error: Exception) -> None:
        self.notes.append(f"lost {self.describe()}: {error}; reconnecting")
        self._retry_at = time.monotonic() + RECONNECT_S

    def close(self) -> None:
        self.client.close()
