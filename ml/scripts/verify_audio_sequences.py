"""Host numeric/parser checks for richer sequence capture; no serial device needed."""
import ctypes
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import runpy
import sys
import tempfile
import types

import numpy as np

from capture_audio_sequences import SequenceParser

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/"firmware/build/audio_sequence_verification"


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    gcc=shutil.which("gcc")
    if not gcc: raise RuntimeError("Host GCC required")
    def load(path,name):
        dll=BUILD/f"{name}.dll"
        subprocess.run([gcc,"-O2","-std=c99","-shared",str(path),"-lm","-o",str(dll)],check=True)
        lib=ctypes.CDLL(str(dll))
        lib.audio_dsp_init.restype=None
        lib.audio_dsp_init()
        lib.audio_dsp_process.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_int32)]
        return lib
    dll_directory=os.add_dll_directory(str(Path(gcc).parent))
    current=load(ROOT/"firmware/audio/audio_dsp.c","sequence_dsp")
    baseline_path=BUILD/"baseline_audio_dsp.c"
    baseline=load(baseline_path,"previous_dsp") if baseline_path.exists() else None
    current.audio_dsp_process_sequence.argtypes=[ctypes.POINTER(ctypes.c_uint16),
        ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(ctypes.c_int16),ctypes.POINTER(ctypes.c_int32)]
    rng=np.random.default_rng(42)
    t=np.arange(8000)/16000
    signals=[("dc",np.full(8000,2048.))]
    signals += [(f"tone{hz}",2048+300*np.sin(2*np.pi*hz*t)) for hz in [250,1000,4000]]
    signals += [("step_tones",2048+300*np.sin(2*np.pi*np.where(t<.25,250,4000)*t))]
    signals += [(f"noise{i}",2048+rng.normal(0,sigma,8000)) for i,sigma in enumerate([1,2,30,200])]
    signals += [(f"random{i}",rng.integers(0,4096,8000)) for i in range(20)]
    peaks=[]
    for name,wave in signals:
        samples=np.ascontiguousarray(np.clip(np.rint(wave),0,4095),np.uint16)
        summary=np.empty(20,np.int32)
        legacy=np.empty(20,np.int32)
        mel=np.empty((48,20),np.int16)
        rms=np.empty(48,np.int32)
        args=(samples.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
              summary.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
              mel.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
              rms.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)))
        assert current.audio_dsp_process_sequence(*args)==1
        current.audio_dsp_process(args[0],legacy.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)))
        assert np.array_equal(summary,legacy),(name,"legacy vs sequence")
        if baseline:
            baseline.audio_dsp_process(args[0],legacy.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)))
            assert np.array_equal(summary,legacy),(name,"previous source vs new source")
        assert (rms>=0).all()
        average=int(rms.astype(np.int64).sum())//48
        variance=int((rms.astype(np.int64)**2).sum())//48-average**2
        assert summary[0]==average and summary[10]==math.isqrt(max(0,variance))
        if name=="dc": assert (mel==-6144).all() and (rms==0).all()
        if name.startswith("tone"): peaks.append(int(mel.astype(float).mean(axis=0).argmax()))
        if name=="step_tones":
            assert mel[:8].astype(float).mean(axis=0).argmax()<mel[-8:].astype(float).mean(axis=0).argmax()
        repeated=mel.copy()
        assert current.audio_dsp_process_sequence(*args)==1 and np.array_equal(repeated,mel)
    assert peaks[0]<peaks[1]<peaks[2]
    for index in range(4):
        invalid=list(args);invalid[index]=None
        assert current.audio_dsp_process_sequence(*invalid)==0

    def lines(window=7):
        yield f"SEQ_BEGIN,1,{window},500000,48,20,1000,3000,524288,20000,0,236000"
        for frame in range(48):
            yield ",".join(map(str,["SEQ_FRAME",window,frame,int(rms[frame]),*mel[frame].tolist()]))
        yield ",".join(map(str,["SEQ_SUMMARY",window,*summary.tolist()]))
        yield f"SEQ_END,{window}"
    parser=SequenceParser()
    result=None
    for line in lines(): result=parser.feed(line)
    assert result and result["mel_log_q8"]==mel.tolist() and result["summary_q8"]==summary.tolist()
    assert result["frame_rms_q8"]==rms.tolist()
    # Truncation, duplicate frames, out-of-range values, mismatched IDs,
    # unsupported versions, and junk must never produce a valid packet.
    packet=list(lines())
    malformed=[packet[:-2]+[packet[-1]],packet[:2]+packet[1:],
               [packet[0],"SEQ_FRAME,8,0,1,"+",".join(["0"]*20),*packet[2:]],
               [packet[0],"SEQ_FRAME,7,0,1,"+",".join(["40000"]*20),*packet[2:]],
               [packet[0].replace("SEQ_BEGIN,1,","SEQ_BEGIN,2,"),*packet[1:]]]
    for bad in malformed:
        parser=SequenceParser()
        assert all(parser.feed(line) is None for line in bad)
        completed=None
        for line in lines(9): completed=parser.feed(line)
        assert completed and completed["window_id"]==9
    # Verify the actual CLI writer exits on Ctrl+C and never overwrites output,
    # using a fake serial port and a temporary file, not a connected Pico.
    class FakeSerial:
        def __init__(self,*a,**kw):self.lines=iter(lines())
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def readline(self,*a):
            try:return (next(self.lines)+"\n").encode()
            except StopIteration:raise KeyboardInterrupt
    saved_serial,saved_args=sys.modules.get("serial"),sys.argv[:]
    try:
        sys.modules["serial"]=types.SimpleNamespace(Serial=FakeSerial,SerialException=OSError)
        with tempfile.TemporaryDirectory(dir=BUILD) as temporary:
            target=Path(temporary)/"capture.jsonl"
            sys.argv=["capture_audio_sequences.py","--label","lecture","--source-id","fixture_video",
                      "--output",str(target)]
            with contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(ROOT/"ml/scripts/capture_audio_sequences.py"),run_name="__main__")
            saved=target.read_text()
            record=json.loads(saved)
            assert record["source_id"]=="fixture_video" and record["label"]=="lecture"
            assert len(record["mel_log_q8"])==48 and len(record["mel_log_q8"][0])==20
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    runpy.run_path(str(ROOT/"ml/scripts/capture_audio_sequences.py"),run_name="__main__")
            except SystemExit as error:
                assert "exists" in str(error).lower()
            else:raise AssertionError("Existing capture was overwritten")
            assert target.read_text()==saved
    finally:
        sys.argv=saved_args
        if saved_serial is None:sys.modules.pop("serial",None)
        else:sys.modules["serial"]=saved_serial
    report=dict(synthetic_signals_checked=len(signals),legacy_summaries_identical=True,
        previous_source_compatibility_checked=baseline is not None,sequence_order_checked=True,
        parser_roundtrip_passed=True,malformed_packet_recovery_cases=len(malformed),
        invalid_pointer_checks_passed=True,ctrl_c_capture_exit_verified=True,
        existing_capture_protection_verified=True,current_dsp_sha256=hashlib.sha256(
            (ROOT/"firmware/audio/audio_dsp.c").read_bytes()).hexdigest())
    (BUILD/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
