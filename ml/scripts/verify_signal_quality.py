"""Verify integer ADC quality metrics and unchanged capture CSV parsing."""
import contextlib
import csv
import ctypes
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import types

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "firmware/build/signal_audit"


class Quality(ctypes.Structure):
    _fields_ = [("minimum", ctypes.c_uint16), ("maximum", ctypes.c_uint16),
                ("mean_q8", ctypes.c_uint32), ("ac_rms_q8", ctypes.c_uint32),
                ("clipped_samples", ctypes.c_uint32)]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    gcc = shutil.which("gcc")
    if not gcc:
        raise RuntimeError("Host GCC required")
    dll = BUILD / "quality_verify.dll"
    subprocess.run([gcc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-shared",
                    str(ROOT / "firmware/audio/audio_signal_quality.c"), "-o", str(dll)], check=True)
    dll_directory = os.add_dll_directory(str(Path(gcc).parent))
    lib = ctypes.CDLL(str(dll))
    ptr = ctypes.POINTER(ctypes.c_uint16)
    lib.audio_signal_quality.argtypes = [ptr, ctypes.c_size_t, ctypes.POINTER(Quality)]
    lib.audio_signal_status.argtypes = [ctypes.POINTER(Quality), ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_int32)]
    lib.audio_signal_status.restype = ctypes.c_char_p
    rng = np.random.default_rng(42)
    cases = {"dc": np.full(8000, 2048),
        "weak_noise": np.rint(2048+rng.normal(0, 1.2, 8000)),
        "tone": np.rint(2048+100*np.sin(2*np.pi*1000*np.arange(8000)/16000)),
        "rails": np.tile([0,4095],4000)}
    results = {}
    for name, values in cases.items():
        values = np.ascontiguousarray(values, np.uint16)
        quality = Quality()
        assert lib.audio_signal_quality(values.ctypes.data_as(ptr), len(values), ctypes.byref(quality)) == 1
        expected = np.sqrt(np.mean((values.astype(float)-values.mean())**2))*256
        assert abs(quality.ac_rms_q8-expected) <= 1.01
        assert quality.minimum == values.min() and quality.maximum == values.max()
        features = np.zeros(20, np.int32)
        if name == "weak_noise":
            features[1], features[4] = 3850*256, 195
        status = lib.audio_signal_status(ctypes.byref(quality), len(values),
            features.ctypes.data_as(ctypes.POINTER(ctypes.c_int32))).decode()
        results[name] = dict(ac_rms_q8=quality.ac_rms_q8, status=status)
    assert results["dc"]["status"] == "LOW_LEVEL"
    assert results["rails"]["status"] == "NEAR_ADC_RAIL"
    assert results["weak_noise"]["status"] == "LOW_LEVEL_BROADBAND"
    assert results["tone"]["status"] == "CHECK_SPEECH_QUALITY"
    assert lib.audio_signal_quality(None, 8000, ctypes.byref(quality)) == 0
    assert lib.audio_signal_quality(values.ctypes.data_as(ptr), 0, ctypes.byref(quality)) == 0
    assert lib.audio_signal_quality(values.ctypes.data_as(ptr), 8001, ctypes.byref(quality)) == 0
    bad = np.full(8000,4096,np.uint16)
    assert lib.audio_signal_quality(bad.ctypes.data_as(ptr),8000,ctypes.byref(quality)) == 0
    assert lib.audio_signal_quality(values.ctypes.data_as(ptr),8000,None) == 0

    # Execute the capture script against a fake serial stream in a temporary
    # directory. No physical port is opened or existing recording overwritten.
    lines = iter([b"SIGNAL_STATUS=LOW_LEVEL_BROADBAND | ADC_AC_RMS_Q8=316\n",
                  b"SIGNAL_STATUS=LOW_LEVEL_BROADBAND | ADC_AC_RMS_Q8=317\n",
                  ("FEATURES_Q8="+",".join(str(i) for i in range(20))+"\n").encode()])
    class FakeSerial:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def readline(self):
            try: return next(lines)
            except StopIteration: raise KeyboardInterrupt
    original_serial, original_cwd = sys.modules.get("serial"), Path.cwd()
    log = io.StringIO()
    try:
        sys.modules["serial"] = types.SimpleNamespace(Serial=FakeSerial)
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            os.chdir(directory)
            with contextlib.redirect_stdout(log):
                namespace = runpy.run_path(str(ROOT / "ml/scripts/capture_csv_fixed.py"))
            with Path(namespace["OUTPUT_FILE"]).open(newline="") as f:
                saved = list(csv.reader(f))
            assert len(saved) == 2 and len(saved[0]) == 22
            assert list(map(int,saved[1][2:])) == list(range(20))
            assert log.getvalue().count("SIGNAL_STATUS=") == 1
            os.chdir(original_cwd)
    finally:
        os.chdir(original_cwd)
        if original_serial is None: sys.modules.pop("serial",None)
        else: sys.modules["serial"] = original_serial
    result = dict(cases=results,numeric_reference_passed=True,invalid_inputs_passed=True,
                  capture_csv_schema_preserved=True,quality_status_deduplicated=True)
    dest = ROOT / "ml/candidates/signal_audit/quality_verification.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2)+"\n")
    print("Passed integer metric references, invalid inputs, capture CSV compatibility and status reporting.")


if __name__ == "__main__":
    main()
