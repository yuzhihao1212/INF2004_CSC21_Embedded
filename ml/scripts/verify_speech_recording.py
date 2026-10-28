"""Test actual C binary transport, live events/WAV matching and stop cleanup."""
import contextlib
import ctypes
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

import numpy as np

from monitor_speech import StreamParser,run_session,ROOT


def main():
    build=ROOT/'firmware/build/speech_stream_verification'
    build.mkdir(parents=True,exist_ok=True)
    gcc=shutil.which('gcc')
    if not gcc:raise RuntimeError('Host GCC required')
    if __import__('os').name=='nt':
        dll_handle=__import__('os').add_dll_directory(str(Path(gcc).parent))
    target=build/'stream.dll'
    subprocess.run([gcc,'-O2','-std=c11','-Wall','-Wextra','-Werror','-Wno-array-parameter',
                    '-shared',str(ROOT/'firmware/audio/audio_stream.c'),'-o',str(target)],check=True)
    lib=ctypes.CDLL(str(target))
    writer_type=ctypes.CFUNCTYPE(None,ctypes.POINTER(ctypes.c_char),ctypes.c_size_t)
    lib.audio_stream_emit.argtypes=[np.ctypeslib.ndpointer(dtype=np.uint16,flags='C_CONTIGUOUS'),
                                    ctypes.c_uint32,ctypes.c_uint64,writer_type]
    lib.audio_stream_emit.restype=ctypes.c_int
    rng=np.random.default_rng(12)
    samples=rng.integers(0,4096,8000,dtype=np.uint16)
    samples[:8]=[0,4095,10,13,2048,1,4094,4093]
    def encode(window):
        parts=[]
        callback=writer_type(lambda p,n:parts.append(ctypes.string_at(p,n)))
        assert lib.audio_stream_emit(samples,window,window*500000,callback)==1
        return b''.join(parts)
    packet=encode(10)
    for size in [1,7,512,8192,len(packet)]:
        parser=StreamParser();items=[]
        for start in range(0,len(packet),size):items.extend(parser.feed(packet[start:start+size]))
        frames=[v for k,v in items if k=='audio']
        assert len(frames)==1 and np.array_equal(frames[0]['samples'],samples)
        assert frames[0]['window']==10 and parser.errors==0
    bad=bytearray(packet)
    bad[bad.index(b'\n')+1]^=1
    parser=StreamParser()
    decoded=list(parser.feed(bytes(bad)+encode(11)))
    assert [v['window'] for k,v in decoded if k=='audio']==[11] and parser.errors==1
    assert not list(StreamParser().feed(packet[:200]))

    class Port:
        def __init__(self,interrupt=False):
            self.data=(b'STREAM_READY,1\n'+encode(10)+
                b'VAD,WINDOW=10,EVENT=TALKING,OVERRUN=0\n'+encode(12)+
                b'VAD,WINDOW=12,EVENT=NO_SPEECH,OVERRUN=0\n')
            self.commands=[];self.interrupt=interrupt
        @property
        def in_waiting(self):return min(1024,len(self.data))
        def reset_input_buffer(self):pass
        def write(self,data):self.commands.append(data)
        def read(self,count):
            if self.interrupt or not self.data:raise KeyboardInterrupt
            value=self.data[:count];self.data=self.data[count:];return value
    with tempfile.TemporaryDirectory(dir=build) as temp:
        folder=Path(temp)/'session';port=Port()
        with contextlib.redirect_stdout(io.StringIO()):report=run_session(port,folder)
        assert report['received_blocks']==2 and report['missing_blocks_filled_with_silence']==1
        assert report['wav_seconds']==1.5 and port.commands==[b's',b'v']
        with wave.open(str(folder/'microphone.wav'),'rb') as wav:
            assert wav.getframerate()==16000 and wav.getnframes()==24000
            pcm=np.frombuffer(wav.readframes(24000),dtype='<i2')
        assert np.array_equal((pcm[:8000].astype(np.int32)//16+2048).astype(np.uint16),samples)
        assert not pcm[8000:16000].any()
        events=[json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines()]
        mapping=[json.loads(s) for s in (folder/'audio_windows.jsonl').read_text().splitlines()]
        assert [e['WINDOW'] for e in events]==['10','12']
        assert [m['wav_start_seconds'] for m in mapping]==[0,1.0]
        cancelled=Port(interrupt=True)
        with contextlib.redirect_stdout(io.StringIO()):result=run_session(cancelled,Path(temp)/'cancelled')
        assert result['received_blocks']==0 and cancelled.commands==[b's',b'v']
        with wave.open(str(Path(temp)/'cancelled/microphone.wav'),'rb') as wav:
            assert wav.getnframes()==0  # Valid, closed header even on immediate Ctrl+C.
    print('PASS: C packed-ADC round trip, binary fragmentation/checksum, same-session WAV/events, gap silence and Ctrl+C closure.')


if __name__=='__main__':main()
