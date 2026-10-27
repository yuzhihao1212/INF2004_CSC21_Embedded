"""MOSAIC node <-> PC wire protocol, version 2.

Python mirror of firmware/common/include/mosaic_protocol.h; the specification
is docs/protocol.md. Keep the two files in step: pc/tests/test_protocol.py
decodes datagrams produced by the C header and fails if they drift apart.

Every UDP datagram is a 16-byte header followed by exactly one payload, all
little-endian with no padding. The wire carries integers only; fractional
values are scaled, and the field suffix says by how much (temperature_x10 is
tenths of a degree). The dataclasses keep the wire integers and add float
properties for display, since the PC has no fixed-point requirement.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass
from typing import Optional, Union

MAGIC = 0x534D  # b"MS" on the wire
PROTOCOL_VERSION = 2

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
AUDIO_WINDOWS_PER_REPORT = 2


class Valid(enum.IntFlag):
    TEMP_HUM = 1 << 0
    CO2 = 1 << 1
    CO2_WARMUP = 1 << 2
    PIR = 1 << 3
    # Bit 4 was AUDIO in v1. Audio validity is now the number of windows.


class Mode(enum.IntEnum):
    LECTURE = 0
    DISCUSSION = 1
    QUIET_WORK = 2


class AckStatus(enum.IntEnum):
    OK = 0
    INVALID_VALUE = 1
    UNSUPPORTED = 2
    STALE_VERSION = 3


# Accepted CONFIG ranges, identical to the C header.
REPORT_INTERVAL_MS = (200, 10000)
DHT_INTERVAL_MS = (2000, 60000)
CO2_INTERVAL_MS = (1000, 60000)
AUDIO_GAIN_X256 = (26, 2560)  # 0.1 .. 10.0


class ProtocolError(ValueError):
    """A datagram that is not a valid MOSAIC v2 message."""


# struct formats; field order matches the C structs exactly.
_HEADER = struct.Struct("<HBBBBHII")    # 16 bytes
_WINDOW = "HB4sB"                       # 8 bytes, mosaic_audio_window_t
_TELEMETRY = struct.Struct("<IIIhHHHHH" + _WINDOW * AUDIO_WINDOWS_PER_REPORT + "BBBBb3s")  # 48
_CONFIG = struct.Struct("<HHHHHBB4s")   # 16 bytes
_CONFIG_ACK = struct.Struct("<HBB")     # 4 bytes
_PING = struct.Struct("<Q")             # 8 bytes


@dataclass
class Header:
    msg_type: MsgType
    node_id: int  # Node -> PC: the sender. PC -> node: the destination.
    seq: int
    sender_time_ms: int
    flags: int = 0
    version: int = PROTOCOL_VERSION


@dataclass
class AudioWindow:
    """One classified 500 ms audio window."""
    rms_x16: int = 0  # Q12.4, ADC units
    audio_class: AudioClass = AudioClass.UNKNOWN
    prob_pct: tuple[int, ...] = (0,) * AUDIO_CLASS_COUNT

    @property
    def rms(self) -> float:
        return self.rms_x16 / 16

    @property
    def confidence_pct(self) -> int:
        """Probability of the reported class (0 when UNKNOWN)."""
        if self.audio_class == AudioClass.UNKNOWN:
            return 0
        return self.prob_pct[self.audio_class - 1]


@dataclass
class Telemetry:
    dsp_time_us: int = 0
    inference_time_us: int = 0
    free_heap_bytes: int = 0
    temperature_x10: int = 0
    humidity_x10: int = 0
    co2_ppm: int = 0
    config_version: int = 0
    audio_overruns: int = 0
    audio_window_seq: int = 0
    audio: tuple[AudioWindow, ...] = ()  # Oldest first, at most AUDIO_WINDOWS_PER_REPORT
    pir_active_pct: int = 0
    valid_flags: Valid = Valid(0)
    cpu_load_pct: int = 0
    wifi_rssi_dbm: int = 0

    @property
    def temperature_c(self) -> float:
        return self.temperature_x10 / 10

    @property
    def humidity_pct(self) -> float:
        return self.humidity_x10 / 10

    @property
    def latest_audio(self) -> Optional[AudioWindow]:
        return self.audio[-1] if self.audio else None


@dataclass
class Config:
    config_version: int
    report_interval_ms: int = 1000
    dht_interval_ms: int = 2500
    co2_interval_ms: int = 2000
    audio_gain_x256: int = 256  # Q8.8, 256 = 1.0
    mode: Mode = Mode.LECTURE
    audio_conf_threshold_pct: int = 60

    @property
    def audio_gain(self) -> float:
        return self.audio_gain_x256 / 256

    def check(self, current_version: int = 0) -> AckStatus:
        """Same rules as mosaic_config_check() on the node."""
        def within(value, bounds):
            return bounds[0] <= value <= bounds[1]

        if self.config_version == 0:
            return AckStatus.INVALID_VALUE
        if self.config_version < current_version:
            return AckStatus.STALE_VERSION
        ok = (
            within(self.report_interval_ms, REPORT_INTERVAL_MS)
            and within(self.dht_interval_ms, DHT_INTERVAL_MS)
            and within(self.co2_interval_ms, CO2_INTERVAL_MS)
            and within(self.audio_gain_x256, AUDIO_GAIN_X256)
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


def _audio_class(value: int) -> AudioClass:
    try:
        return AudioClass(value)
    except ValueError:
        raise ProtocolError(f"unknown audio class {value}") from None


def _encode_telemetry(t: Telemetry) -> bytes:
    if len(t.audio) > AUDIO_WINDOWS_PER_REPORT:
        raise ValueError(f"at most {AUDIO_WINDOWS_PER_REPORT} audio windows per report")
    windows = []
    for i in range(AUDIO_WINDOWS_PER_REPORT):
        w = t.audio[i] if i < len(t.audio) else AudioWindow()  # Unused slots are 0
        probs = bytes(w.prob_pct)
        if len(probs) != AUDIO_CLASS_COUNT:
            raise ValueError(f"prob_pct needs {AUDIO_CLASS_COUNT} values")
        windows += [w.rms_x16, w.audio_class, probs, 0]
    return _TELEMETRY.pack(
        t.dsp_time_us, t.inference_time_us, t.free_heap_bytes,
        t.temperature_x10, t.humidity_x10, t.co2_ppm, t.config_version,
        t.audio_overruns, t.audio_window_seq, *windows, len(t.audio),
        t.pir_active_pct, t.valid_flags, t.cpu_load_pct, t.wifi_rssi_dbm, b"\0" * 3,
    )


def _decode_telemetry(body: bytes) -> Telemetry:
    fields = _TELEMETRY.unpack(body)
    head, window_fields, tail = fields[:9], fields[9:-6], fields[-6:]
    count, pir_pct, valid, cpu, rssi, _reserved = tail
    if count > AUDIO_WINDOWS_PER_REPORT:
        raise ProtocolError(f"audio_window_count {count} > {AUDIO_WINDOWS_PER_REPORT}")
    windows = tuple(
        AudioWindow(rms, _audio_class(audio_class), tuple(probs))
        for rms, audio_class, probs, _reserved in
        (window_fields[i * 4:i * 4 + 4] for i in range(count)))
    return Telemetry(*head, windows, pir_pct, Valid(valid), cpu, rssi)


def encode(header: Header, payload: Payload) -> bytes:
    """Serialise one datagram."""
    msg_type = MsgType(header.msg_type)
    _payload_type(payload, msg_type)

    if isinstance(payload, Telemetry):
        body = _encode_telemetry(payload)
    elif isinstance(payload, Config):
        body = _CONFIG.pack(
            payload.config_version, payload.report_interval_ms,
            payload.dht_interval_ms, payload.co2_interval_ms, payload.audio_gain_x256,
            payload.mode, payload.audio_conf_threshold_pct, b"\0" * 4,
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
        payload: Payload = _decode_telemetry(body)
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
