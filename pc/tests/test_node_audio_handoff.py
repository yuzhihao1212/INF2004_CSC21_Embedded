"""Compile the real C mailbox and pass its output through the PC decoder."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from mosaic import protocol as p
from mosaic.gateway import Gateway


class AudioHandoff(unittest.TestCase):
    def test_queue_gaps_bounds_and_c_wire_packet(self):
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            self.skipTest("host C compiler unavailable")
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as d:
            exe = str(pathlib.Path(d) / "handoff_test")
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(root / "firmware/node"),
                            "-I" + str(root / "firmware/common/include"),
                            str(root / "firmware/common/test/audio_handoff_test.c"),
                            "-o", exe], check=True, capture_output=True)
            wire = subprocess.run([exe], check=True, capture_output=True).stdout
        gateway = Gateway()
        result = gateway.handle(wire, ("192.0.2.1", 5006), 1.0)
        self.assertIsNotNone(result)
        telemetry = gateway.nodes[1].telemetry
        self.assertEqual(len(telemetry.audio), 2)
        self.assertEqual(telemetry.audio_window_seq, 2)
        self.assertEqual([w.rms_x16 for w in telemetry.audio], [160, 320])
        self.assertEqual(telemetry.audio[1].audio_class, p.AudioClass.TRANSIENT_NOISE)
        self.assertEqual((telemetry.dsp_time_us, telemetry.inference_time_us), (123, 21))
