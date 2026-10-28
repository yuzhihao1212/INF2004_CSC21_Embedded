"""C transport -> Python parser/CLI -> upstream model replay, without hardware."""
import contextlib
import ctypes
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

import numpy as np

import diagnose_microphone as diagnostic
from verify_pulsevad import ROOT, BUILD, load_c, U16


def main():
    lib=load_c()
    # Compile the real firmware encoder, not a Python mirror of its format.
    gcc=__import__('shutil').which('gcc')
    path=BUILD/'raw_encoder.dll'
    subprocess.run([gcc,'-std=c11','-O2','-Wall','-Wextra','-Werror',
                    '-Wno-array-parameter','-shared',
                    str(ROOT/'firmware/audio/audio_raw_diagnostic.c'),'-o',str(path)],check=True)
    encoder=ctypes.CDLL(str(path))
    writer_type=ctypes.CFUNCTYPE(None,ctypes.POINTER(ctypes.c_char),ctypes.c_size_t)
    encoder.audio_raw_diagnostic_emit.argtypes=[U16,ctypes.c_uint32,ctypes.c_uint64,
                                               ctypes.c_float,ctypes.c_float,writer_type]
    encoder.audio_raw_diagnostic_emit.restype=ctypes.c_int
    rng=np.random.default_rng(51)
    rows=[]
    for i in range(16):
        signal=rng.normal(0,3 if i<4 else 120,8000)
        adc=np.clip(np.rint(signal+2048),0,4095).astype(np.uint16)
        embedding=np.empty(8,np.float32)
        probability=lib.pulsevad_process_adc(adc[:3200],embedding)
        lib.talking_head_probability.argtypes=[np.ctypeslib.ndpointer(dtype=np.float32,flags='C_CONTIGUOUS')]
        lib.talking_head_probability.restype=ctypes.c_float
        own=lib.talking_head_probability(embedding)
        parts=[]
        callback=writer_type(lambda data,count:parts.append(ctypes.string_at(data,count)))
        assert encoder.audio_raw_diagnostic_emit(adc,100+i,500000*i,probability,own,callback)==1
        lines=b''.join(parts).decode('ascii').splitlines()
        parser=diagnostic.RawParser()
        packets=[p for line in lines if (p:=parser.feed(line)) is not None]
        assert len(packets)==1 and parser.discarded==0
        assert packets[0]['samples']==adc.tolist()
        rows.append(lines)
    first=rows[0]
    parts=[]
    callback=writer_type(lambda data,count:parts.append(ctypes.string_at(data,count)))
    assert encoder.audio_raw_diagnostic_emit(adc,500,500000,-1,-1,callback)==1
    parser=diagnostic.RawParser()
    baseline=[p for line in b''.join(parts).decode().splitlines() if (p:=parser.feed(line)) is not None]
    assert len(baseline)==1 and baseline[0]['board_pulse'] is None and baseline[0]['board_own'] is None
    assert encoder.audio_raw_diagnostic_emit(adc,500,500000,-1,.5,callback)==0
    encoded=('\r\n'.join(first)+'\r\n').encode()
    for size in [1,3,127,1024,8192]:
        buffer=diagnostic.LineBuffer()
        decoded=[]
        for start in range(0,len(encoded),size):
            decoded.extend(buffer.feed(encoded[start:start+size]))
        assert decoded==first and not buffer.pending
        assert buffer.oversized==0
    for broken in [first[:2]+first[3:],first[:2]+[first[1]]+first[2:],
                   first[:-1]+['RAW_END,100,1'],
                   [first[0],first[1][:-1]]+first[2:]]:
        parser=diagnostic.RawParser()
        assert not any(parser.feed(line) for line in broken)
        recovered=[p for line in rows[1] if (p:=parser.feed(line)) is not None]
        assert len(recovered)==1 and recovered[0]['window']==101
    # Run the actual CLI against a fake serial connection; verify command,
    # complete capture, resource release and report/WAV creation.
    class FakeSerial:
        def __init__(self,*args,**kwargs):
            self.buffer=b'RAW_READY,16\n'+b''.join(f'{line}\n'.encode() for block in rows for line in block)+b'RAW_DONE\n'
            self.commands=[]
            self.closed=False
        def __enter__(self): return self
        def __exit__(self,*args): self.closed=True
        def write(self,data): self.commands.append(data)
        def reset_input_buffer(self): pass
        @property
        def in_waiting(self): return min(len(self.buffer),4096)
        def read(self,count):
            result=self.buffer[:count]
            self.buffer=self.buffer[count:]
            return result
    port=FakeSerial()
    original_serial=sys.modules.get('serial')
    original_argv=sys.argv[:]
    sys.modules['serial']=types.SimpleNamespace(Serial=lambda *a,**k:port,SerialException=OSError)
    try:
        with tempfile.TemporaryDirectory(dir=BUILD) as tmp:
            output=Path(tmp)/'capture'
            sys.argv=['diagnose_microphone.py','--output',str(output)]
            messages=io.StringIO()
            with contextlib.redirect_stdout(messages):
                diagnostic.main()
            assert 'Audio received: 16/16 blocks.' in messages.getvalue()
            report=__import__('json').loads((output/'report.json').read_text())
            assert report['complete_capture']
            assert report['max_board_pc_pulse_difference']<.001
            assert report['max_board_pc_own_difference']<.001
            assert (output/'microphone.wav').exists() and (output/'raw_adc.npz').exists()
            assert port.closed and port.commands==[b'r',b'v']
            transport=__import__('json').loads((output/'transport_report.json').read_text())
            assert transport['valid_blocks']==16 and transport['discarded_blocks']==0
            assert transport['lines']['RAW_DATA']==16*63
            # The recording-only CLI must work without any model/vendor paths.
            record_port=FakeSerial()
            sys.modules['serial'].Serial=lambda *a,**k:record_port
            sys.argv=['diagnose_microphone.py','--record-only','--output',str(Path(tmp)/'record_only')]
            original_vendor=diagnostic.VENDOR
            diagnostic.VENDOR=Path(tmp)/'no_models_here'
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    diagnostic.main()
            finally:
                diagnostic.VENDOR=original_vendor
            assert (Path(tmp)/'record_only/microphone.wav').exists()
            assert not (Path(tmp)/'record_only/scores.csv').exists()
            assert record_port.closed and record_port.commands==[b'r',b'v']
            cancelled=FakeSerial()
            def interrupt(*args): raise KeyboardInterrupt
            cancelled.read=interrupt
            sys.modules['serial'].Serial=lambda *a,**k:cancelled
            sys.argv=['diagnose_microphone.py','--output',str(Path(tmp)/'cancelled')]
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    diagnostic.main()
                except SystemExit:
                    pass
            assert cancelled.closed and cancelled.commands==[b'r',b'v']
    finally:
        sys.argv=original_argv
        if original_serial is None: sys.modules.pop('serial',None)
        else: sys.modules['serial']=original_serial
    print('PASS: C/Python raw round trips; fragmented bulk input; malformed recovery; upstream replay; progress, transport report and Ctrl+C release.')


if __name__=='__main__':
    main()
