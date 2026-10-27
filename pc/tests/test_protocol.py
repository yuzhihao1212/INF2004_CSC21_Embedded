"""Tests for pc/mosaic/protocol.py, including a cross-check against the C header.

Run from the pc/ folder:  python -m unittest -v
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mosaic import protocol as p

REPO = Path(__file__).resolve().parents[2]
C_INCLUDE = REPO / "firmware" / "common" / "include"
C_DUMP = REPO / "firmware" / "common" / "test" / "protocol_dump.c"


class RoundTrip(unittest.TestCase):
    def test_telemetry(self):
        header = p.Header(p.MsgType.TELEMETRY, node_id=2, seq=10, sender_time_ms=5000)
        payload = p.Telemetry(
            temperature_x10=245, humidity_x10=550, co2_ppm=650, audio_window_seq=9,
            audio=(p.AudioWindow(48, p.AudioClass.STUDENT_CONVERSATION, (10, 5, 70, 15)),),
            pir_active_pct=40, valid_flags=p.Valid.TEMP_HUM, wifi_rssi_dbm=-61)
        data = p.encode(header, payload)
        self.assertEqual(len(data), 64)
        self.assertEqual(p.decode(data), (header, payload))
        self.assertEqual((payload.temperature_c, payload.humidity_pct), (24.5, 55.0))
        self.assertEqual(payload.latest_audio.rms, 3.0)
        self.assertEqual(payload.latest_audio.confidence_pct, 70)

    def test_no_audio_windows(self):
        header = p.Header(p.MsgType.TELEMETRY, node_id=2, seq=10, sender_time_ms=5000)
        payload = p.Telemetry(temperature_x10=-400)
        self.assertEqual(p.decode(p.encode(header, payload)), (header, payload))
        self.assertIsNone(payload.latest_audio)

    def test_too_many_audio_windows(self):
        header = p.Header(p.MsgType.TELEMETRY, 1, 0, 0)
        with self.assertRaises(ValueError):
            p.encode(header, p.Telemetry(audio=(p.AudioWindow(),) * 3))
        data = bytearray(p.encode(header, p.Telemetry()))
        data[16 + 40] = 3  # audio_window_count
        with self.assertRaises(p.ProtocolError):
            p.decode(bytes(data))

    def test_config_ack_ping(self):
        cases = [
            (p.MsgType.CONFIG, p.Config(config_version=3, mode=p.Mode.QUIET_WORK,
                                        audio_gain_x256=512)),
            (p.MsgType.CONFIG_ACK, p.ConfigAck(3, p.AckStatus.INVALID_VALUE)),
            (p.MsgType.PING, p.Ping(987654321)),
            (p.MsgType.PONG, p.Ping(987654321)),
        ]
        for msg_type, payload in cases:
            with self.subTest(msg_type=msg_type.name):
                header = p.Header(msg_type, node_id=0, seq=1, sender_time_ms=1)
                self.assertEqual(p.decode(p.encode(header, payload)), (header, payload))

    def test_wrong_payload_type_rejected(self):
        header = p.Header(p.MsgType.CONFIG, 0, 0, 0)
        with self.assertRaises(TypeError):
            p.encode(header, p.Ping())


class Malformed(unittest.TestCase):
    def setUp(self):
        self.good = p.encode(p.Header(p.MsgType.PING, 0, 0, 0), p.Ping(1))

    def test_too_short(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(self.good[:10])

    def test_bad_magic(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(b"XX" + self.good[2:])

    def test_wrong_version(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(self.good[:2] + bytes([1]) + self.good[3:])  # v1

    def test_unknown_type(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(self.good[:3] + bytes([99]) + self.good[4:])

    def test_truncated_payload(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(self.good[:-1])

    def test_trailing_bytes(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(self.good + b"\0")


class ConfigRanges(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(p.Config(config_version=1).check(), p.AckStatus.OK)

    def test_out_of_range(self):
        bad = [
            dict(config_version=0),
            dict(report_interval_ms=199),
            dict(report_interval_ms=10001),
            dict(dht_interval_ms=1999),
            dict(co2_interval_ms=999),
            dict(audio_gain_x256=25),
            dict(audio_gain_x256=2561),
            dict(mode=3),
            dict(audio_conf_threshold_pct=101),
        ]
        for change in bad:
            with self.subTest(**{k: str(v) for k, v in change.items()}):
                fields = dict(config_version=1) | change
                self.assertEqual(p.Config(**fields).check(), p.AckStatus.INVALID_VALUE)

    def test_bounds_inclusive(self):
        cfg = p.Config(config_version=1, report_interval_ms=200, dht_interval_ms=2000,
                       co2_interval_ms=1000, audio_gain_x256=26, audio_conf_threshold_pct=100)
        self.assertEqual(cfg.check(), p.AckStatus.OK)
        self.assertEqual(p.Config(config_version=1, audio_gain_x256=2560).check(), p.AckStatus.OK)

    def test_version_ordering(self):
        cfg = p.Config(config_version=7)
        self.assertEqual(cfg.check(current_version=6), p.AckStatus.OK)
        self.assertEqual(cfg.check(current_version=7), p.AckStatus.OK)  # Retry
        self.assertEqual(cfg.check(current_version=8), p.AckStatus.STALE_VERSION)
        # Stale is reported even when a field is also out of range.
        bad = p.Config(config_version=7, report_interval_ms=1)
        self.assertEqual(bad.check(current_version=8), p.AckStatus.STALE_VERSION)


@unittest.skipUnless(shutil.which("cc"), "no host C compiler")
class MatchesCHeader(unittest.TestCase):
    """Decode datagrams built by firmware/common/test/protocol_dump.c."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "protocol_dump"
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", f"-I{C_INCLUDE}",
                 str(C_DUMP), "-o", str(exe)], check=True)
            out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
        cls.packets = {name: bytes.fromhex(hexdata)
                       for name, hexdata in (line.split() for line in out.splitlines())}

    def test_telemetry(self):
        header, t = p.decode(self.packets["telemetry"])
        self.assertEqual(header, p.Header(p.MsgType.TELEMETRY, 3, 42, 123456,
                                          flags=p.FLAG_FIRST_SINCE_BOOT))
        self.assertEqual(t, p.Telemetry(
            temperature_x10=-55, humidity_x10=612,
            dsp_time_us=81000, inference_time_us=950, free_heap_bytes=65536,
            co2_ppm=812, config_version=7, audio_overruns=2, audio_window_seq=301,
            audio=(p.AudioWindow(200, p.AudioClass.LECTURER_SPEECH, (5, 80, 10, 5)),
                   p.AudioWindow(0xFFFF, p.AudioClass.UNKNOWN, (30, 40, 20, 10))),
            pir_active_pct=35, valid_flags=p.Valid.TEMP_HUM | p.Valid.CO2 | p.Valid.PIR,
            cpu_load_pct=63, wifi_rssi_dbm=-58))
        self.assertEqual(t.temperature_c, -5.5)
        self.assertEqual(t.audio[0].rms, 12.5)

    def test_config(self):
        header, c = p.decode(self.packets["config"])
        self.assertEqual(header, p.Header(p.MsgType.CONFIG, 3, 9, 5000))
        self.assertEqual(c, p.Config(config_version=7, mode=p.Mode.DISCUSSION, audio_gain_x256=384))
        self.assertEqual(c.audio_gain, 1.5)
        self.assertEqual(c.check(), p.AckStatus.OK)
        # The C defaults must equal the Python defaults.
        self.assertEqual(p.encode(header, c), self.packets["config"])

    def test_config_ack(self):
        header, a = p.decode(self.packets["config_ack"])
        self.assertEqual(header, p.Header(p.MsgType.CONFIG_ACK, 3, 43, 123500))
        self.assertEqual(a, p.ConfigAck(7, p.AckStatus.OK))

    def test_pong(self):
        header, ping = p.decode(self.packets["pong"])
        self.assertEqual(header, p.Header(p.MsgType.PONG, 3, 44, 123600))
        self.assertEqual(ping, p.Ping(1234567890123))

    def test_python_encodes_identical_bytes(self):
        for name in ("telemetry", "config", "config_ack", "pong"):
            with self.subTest(name):
                self.assertEqual(p.encode(*p.decode(self.packets[name])), self.packets[name])


if __name__ == "__main__":
    unittest.main()
