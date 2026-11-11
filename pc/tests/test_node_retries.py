"""Exercise the actual allocation-free C retry scheduler with the host compiler."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest


class NodeRetries(unittest.TestCase):
    def test_c_scheduler_bounds_expiry_and_owned_payloads(self):
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            self.skipTest("host C compiler unavailable")
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as d:
            exe = str(pathlib.Path(d) / "retry_test")
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(root / "firmware/node"),
                            "-I" + str(root / "firmware/common/include"),
                            str(root / "firmware/common/test/telemetry_retry_test.c"),
                            "-o", exe], check=True, capture_output=True)
            subprocess.run([exe], check=True, capture_output=True)
