"""Run real subsystem 5 C logic and cross-check its wire bytes with the PC."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from mosaic import protocol as p
from mosaic.gateway import Gateway


class Subsystem5Protocol(unittest.TestCase):
    def test_logic_cases_and_c_python_wire_agreement(self):
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            self.skipTest("host C compiler unavailable")
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            exe = str(pathlib.Path(directory) / "s5_protocol_test")
            compiled = subprocess.run([
                cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I" + str(root / "firmware/common/include"),
                str(root / "node/testing/subsystem5/host/s5_protocol_host_test.c"),
                str(root / "node/app_program/subsystem5/s5_protocol.c"),
                "-o", exe,
            ], capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            ran = subprocess.run([exe], capture_output=True)
            self.assertEqual(ran.returncode, 0, ran.stderr.decode())
            wire = ran.stdout
        self.assertEqual(len(wire), 84)
        header, t = p.decode(wire[:64])
        self.assertEqual((header.msg_type, header.node_id, header.seq, header.sender_time_ms),
                         (p.MsgType.TELEMETRY, 1, 0, 1000))
        self.assertEqual(header.flags, p.FLAG_FIRST_SINCE_BOOT)
        self.assertEqual((t.temperature_x10, t.humidity_x10, t.co2_ppm), (251, 657, 850))
        self.assertEqual(t.valid_flags, p.Valid.TEMP_HUM | p.Valid.CO2 | p.Valid.PIR)
        self.assertEqual(t.pir_active_pct, 30)
        self.assertEqual((t.config_version, t.audio_window_seq, t.audio_overruns), (7, 2, 0))
        self.assertEqual([w.rms_x16 for w in t.audio], [160, 320])
        self.assertEqual([w.audio_class for w in t.audio],
                         [p.AudioClass.SPEECH, p.AudioClass.TRANSIENT_NOISE])
        self.assertEqual([tuple(w.prob_pct) for w in t.audio], [(5, 90, 0, 5), (5, 5, 0, 90)])
        self.assertEqual((t.dsp_time_us, t.inference_time_us), (123, 21))
        self.assertEqual((t.wifi_rssi_dbm, t.cpu_load_pct, t.free_heap_bytes), (-65, 42, 123456))
        self.assertEqual(wire[61:64], b"\0" * 3)
        ack_header, ack = p.decode(wire[64:])
        self.assertEqual((ack_header.msg_type, ack_header.node_id, ack_header.seq,
                          ack_header.sender_time_ms), (p.MsgType.CONFIG_ACK, 1, 1, 42))
        self.assertEqual((ack.config_version, ack.status), (7, p.AckStatus.OK))
        self.assertEqual(wire[-1], 0)
        gateway = Gateway()
        self.assertIsNotNone(gateway.handle(wire[:64], ("192.0.2.1", 5006), 1.0))
        self.assertIsNotNone(gateway.handle(wire[64:], ("192.0.2.1", 5006), 1.1))
        self.assertEqual(gateway.nodes[1].telemetry, t)
        self.assertEqual(gateway.nodes[1].last_ack, ack)
