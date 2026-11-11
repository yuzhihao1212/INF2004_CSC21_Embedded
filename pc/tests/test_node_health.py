"""Run the firmware's actual watchdog feed gate on the host."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest


class NodeHealth(unittest.TestCase):
    def test_progress_from_every_task_required_in_each_epoch(self):
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            self.skipTest("host C compiler unavailable")
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            exe = str(pathlib.Path(directory) / "health_test")
            for enabled in ([], ["-DMOSAIC_NODE_AUDIO_ENABLED=1"]):
                subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", *enabled,
                            "-I" + str(root / "firmware/node"),
                            str(root / "firmware/common/test/task_health_test.c"),
                            "-o", exe], check=True, capture_output=True)
                subprocess.run([exe], check=True, capture_output=True)
