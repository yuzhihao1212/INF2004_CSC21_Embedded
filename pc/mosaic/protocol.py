"""MOSAIC node <-> PC wire protocol, version 1.

Python mirror of firmware/common/include/mosaic_protocol.h; the specification
is docs/protocol.md. Keep the two files in step: pc/tests/test_protocol.py
decodes datagrams produced by the C header and fails if they drift apart.

Every UDP datagram is a 16-byte header followed by exactly one payload, all
little-endian with no padding.
"""

from __future__ import annotations

import enum
import math
import struct
from dataclasses import dataclass, field
from typing import Union

MAGIC = 0x534D  # b"MS" on the wire
PROTOCOL_VERSION = 1

PORT_TELEMETRY = 5005  # PC listens: TELEMETRY, CONFIG_ACK, PONG
PORT_CONFIG = 5006     # Node listens: CONFIG, PING

MAX_DATAGRAM = 128
MAX_NODES = 8


class MsgType(enum.IntEnum):
    TELEMETRY = 1
    CONFIG = 2
    CONFIG_ACK = 3
    PING = 4
    PONG = 5


FLAG_FIRST_SINCE_BOOT = 1 << 0


class AudioClass(enum.IntEnum):
    UNKNOWN = 0
    BACKGROUND_NOISE = 1
    LECTURER_SPEECH = 2
    STUDENT_CONVERSATION = 3
    TRANSIENT_NOISE = 4


AUDIO_CLASS_COUNT = 4  # Classes 1..4; probability index = class - 1


class Valid(enum.IntFlag):
    TEMP_HUM = 1 << 0
    CO2 = 1 << 1
    CO2_WARMUP = 1 << 2
    PIR = 1 << 3
    AUDIO = 1 << 4


class Mode(enum.IntEnum):
    LECTURE = 0
    DISCUSSION = 1
    QUIET_WORK = 2


class AckStatus(enum.IntEnum):
    OK = 0
    INVALID_VALUE = 1
    UNSUPPORTED = 2


# Accepted CONFIG ranges, identical to the C header.
REPORT_INTERVAL_MS = (200, 10000)
DHT_INTERVAL_MS = (2000, 60000)
CO2_INTERVAL_MS = (1000, 60000)
AUDIO_GAIN = (0.1, 10.0)


class ProtocolError(ValueError):
    """A datagram that is not a valid MOSAIC v1 message."""


# struct formats; field order matches the C structs exactly.
_HEADER = struct.Struct("<HBBBBHII")              # 16 bytes
_TELEMETRY = struct.Struct("<fffIIIHHHBB4sBBbB")  # 40 bytes
_CONFIG = struct.Struct("<HHHHfBB2s")             # 16 bytes
_CONFIG_ACK = struct.Struct("<HBB")               # 4 bytes
_PING = struct.Struct("<Q")                       # 8 bytes


@dataclass
class Header:
    msg_type: MsgType
    node_id: int
    seq: int
    sender_time_ms: int
    flags: int = 0
    version: int = PROTOCOL_VERSION


@dataclass
class Telemetry:
    temperature_c: float = 0.0
    humidity_pct: float = 0.0
    audio_rms: float = 0.0
    dsp_time_us: int = 0
    inference_time_us: int = 0
    free_heap_bytes: int = 0
    co2_ppm: int = 0
    config_version: int = 0
    audio_overruns: int = 0
    audio_class: AudioClass = AudioClass.UNKNOWN
    pir_active_pct: int = 0
    audio_prob_pct: tuple[int, ...] = (0,) * AUDIO_CLASS_COUNT
    valid_flags: Valid = Valid(0)
    cpu_load_pct: int = 0
    wifi_rssi_dbm: int = 0

    @property
    def audio_confidence_pct(self) -> int:
        """Probability of the reported class (0 when UNKNOWN)."""
        if self.audio_class == AudioClass.UNKNOWN:
            return 0
        return self.audio_prob_pct[self.audio_class - 1]


@dataclass
class Config:
    config_version: int
    report_interval_ms: int = 1000
    dht_interval_ms: int = 2500
    co2_interval_ms: int = 2000
    audio_gain: float = 1.0
    mode: Mode = Mode.LECTURE
    audio_conf_threshold_pct: int = 60

    def check(self) -> AckStatus:
        """Same rules as mosaic_config_check() on the node."""
        def within(value, bounds):
            return bounds[0] <= value <= bounds[1]

        ok = (
            self.config_version != 0
            and within(self.report_interval_ms, REPORT_INTERVAL_MS)
            and within(self.dht_interval_ms, DHT_INTERVAL_MS)
            and within(self.co2_interval_ms, CO2_INTERVAL_MS)
            and not math.isnan(self.audio_gain)
            # Compare as float32, the precision the node receives.
            and within(_f32(self.audio_gain), (_f32(AUDIO_GAIN[0]), _f32(AUDIO_GAIN[1])))
            and self.mode in Mode.__members__.values()
            and 0 <= self.audio_conf_threshold_pct <= 100
        )
        return AckStatus.OK if ok else AckStatus.INVALID_VALUE


@dataclass
class ConfigAck:
    config_version: int
    status: AckStatus = AckStatus.OK


@dataclass
class Ping:
    """Payload of both PING (PC -> node) and PONG (node -> PC)."""
    pc_time_us: int = 0


Payload = Union[Telemetry, Config, ConfigAck, Ping]

_PAYLOAD_SIZE = {
    MsgType.TELEMETRY: _TELEMETRY.size,
    MsgType.CONFIG: _CONFIG.size,
    MsgType.CONFIG_ACK: _CONFIG_ACK.size,
    MsgType.PING: _PING.size,
    MsgType.PONG: _PING.size,
}


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _payload_type(payload: Payload, msg_type: MsgType) -> None:
    expected = {
        MsgType.TELEMETRY: Telemetry,
        MsgType.CONFIG: Config,
        MsgType.CONFIG_ACK: ConfigAck,
        MsgType.PING: Ping,
        MsgType.PONG: Ping,
    }[msg_type]
    if not isinstance(payload, expected):
        raise TypeError(f"{msg_type.name} needs a {expected.__name__} payload")


def encode(header: Header, payload: Payload) -> bytes:
    """Serialise one datagram."""
    msg_type = MsgType(header.msg_type)
    _payload_type(payload, msg_type)

    if isinstance(payload, Telemetry):
        probs = bytes(payload.audio_prob_pct)
        if len(probs) != AUDIO_CLASS_COUNT:
            raise ValueError(f"audio_prob_pct needs {AUDIO_CLASS_COUNT} values")
        body = _TELEMETRY.pack(
            payload.temperature_c, payload.humidity_pct, payload.audio_rms,
            payload.dsp_time_us, payload.inference_time_us, payload.free_heap_bytes,
            payload.co2_ppm, payload.config_version, payload.audio_overruns,
            payload.audio_class, payload.pir_active_pct, probs,
            payload.valid_flags, payload.cpu_load_pct, payload.wifi_rssi_dbm, 0,
        )
    elif isinstance(payload, Config):
        body = _CONFIG.pack(
            payload.config_version, payload.report_interval_ms,
            payload.dht_interval_ms, payload.co2_interval_ms, payload.audio_gain,
            payload.mode, payload.audio_conf_threshold_pct, b"\0\0",
        )
    elif isinstance(payload, ConfigAck):
        body = _CONFIG_ACK.pack(payload.config_version, payload.status, 0)
    else:
        body = _PING.pack(payload.pc_time_us)

    head = _HEADER.pack(
        MAGIC, header.version, msg_type, header.node_id, header.flags,
        len(body), header.seq, header.sender_time_ms,
    )
    return head + body


def decode(data: bytes) -> tuple[Header, Payload]:
    """Parse one datagram. Raises ProtocolError if it is malformed."""
    if len(data) < _HEADER.size:
        raise ProtocolError(f"datagram too short ({len(data)} bytes)")
    magic, version, msg_type, node_id, flags, payload_len, seq, time_ms = (
        _HEADER.unpack_from(data))
    if magic != MAGIC:
        raise ProtocolError(f"bad magic 0x{magic:04x}")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")
    try:
        msg_type = MsgType(msg_type)
    except ValueError:
        raise ProtocolError(f"unknown message type {msg_type}") from None
    expected = _PAYLOAD_SIZE[msg_type]
    if payload_len != expected or len(data) != _HEADER.size + expected:
        raise ProtocolError(
            f"{msg_type.name}: expected {expected}-byte payload, header says "
            f"{payload_len}, datagram has {len(data) - _HEADER.size}")

    header = Header(msg_type, node_id, seq, time_ms, flags, version)
    body = data[_HEADER.size:]

    if msg_type == MsgType.TELEMETRY:
        (temp, hum, rms, dsp_us, inf_us, heap, co2, cfg_ver, overruns,
         audio_class, pir_pct, probs, valid, cpu, rssi, _reserved) = _TELEMETRY.unpack(body)
        try:
            audio_class = AudioClass(audio_class)
        except ValueError:
            raise ProtocolError(f"unknown audio class {audio_class}") from None
        payload: Payload = Telemetry(
            temp, hum, rms, dsp_us, inf_us, heap, co2, cfg_ver, overruns,
            audio_class, pir_pct, tuple(probs), Valid(valid), cpu, rssi)
    elif msg_type == MsgType.CONFIG:
        ver, report, dht, co2, gain, mode, threshold, _reserved = _CONFIG.unpack(body)
        try:
            mode = Mode(mode)
        except ValueError:
            raise ProtocolError(f"unknown mode {mode}") from None
        payload = Config(ver, report, dht, co2, gain, mode, threshold)
    elif msg_type == MsgType.CONFIG_ACK:
        ver, status, _reserved = _CONFIG_ACK.unpack(body)
        try:
            status = AckStatus(status)
        except ValueError:
            raise ProtocolError(f"unknown ack status {status}") from None
        payload = ConfigAck(ver, status)
    else:
        (pc_time_us,) = _PING.unpack(body)
        payload = Ping(pc_time_us)

    return header, payload
