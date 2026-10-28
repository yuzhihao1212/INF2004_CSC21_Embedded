"""Check embedded frontend and complete neural network against upstream ONNX."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'firmware/audio/pulsevad/vendor'
BUILD = ROOT / 'firmware/build/pulsevad_host'
F32 = np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS')
U16 = np.ctypeslib.ndpointer(dtype=np.uint16, flags='C_CONTIGUOUS')


def load_c(parallel=False):
    BUILD.mkdir(parents=True, exist_ok=True)
    gcc = shutil.which('gcc')
    if not gcc:
        raise RuntimeError('Host GCC required')
    target = BUILD / ('pulsevad_parallel.dll' if parallel else 'pulsevad.dll')
    sources = [str(ROOT / 'firmware/audio/pulsevad/pulsevad.c')]
    if (ROOT/'firmware/audio/pulsevad/talking_head.h').exists():
        sources.append(str(ROOT/'firmware/audio/pulsevad/talking_detector.c'))
    flags = ['-DPULSEVAD_HOST_PARALLEL=1','-pthread'] if parallel else []
    subprocess.run([gcc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', *flags,
                    '-Wno-array-parameter', '-shared', *sources, '-lm', '-o', str(target)], check=True)
    if os.name == 'nt':
        handle = os.add_dll_directory(str(Path(gcc).parent))
    lib = ctypes.CDLL(str(target))
    if os.name == 'nt':
        lib.dll_directory_handle = handle
    lib.pulsevad_frontend.argtypes = [F32, F32]
    lib.pulsevad_predict.argtypes = [F32, F32, F32]
    lib.pulsevad_process_adc.argtypes = [U16, F32]
    lib.pulsevad_process_adc.restype = ctypes.c_float
    return lib


def main():
    lib = load_c()
    parallel_lib = load_c(parallel=True)
    spec = importlib.util.spec_from_file_location('reference_frontend', VENDOR/'frontend_np.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    reference._MEL_FB = np.load(VENDOR/'mel_filterbank.npy')
    session = ort.InferenceSession(str(VENDOR/'pulsevad_2.1k.onnx'), providers=['CPUExecutionProvider'])
    rng = np.random.default_rng(92)
    time = np.arange(3200)/16000
    signals = [np.zeros(3200), rng.normal(0,.03,3200), rng.uniform(-.5,.5,3200)]
    signals += [.3*np.sin(2*np.pi*f*time) for f in [125,440,1000,3000,7500]]
    signals += [.1*np.sin(2*np.pi*220*time)*(1+.8*np.sin(2*np.pi*7*time))]
    signals += [np.r_[np.zeros(1600), rng.normal(0,.1,1600)]]
    for index in [0,1,199,1600,3199]:
        impulse = np.zeros(3200,np.float32)
        impulse[index] = .99
        signals.append(impulse)
    public_manifest = ROOT/'ml/data/vad_public/manifest.json'
    public_count = 0
    if public_manifest.exists():
        import soundfile as sf
        from scipy.signal import resample_poly
        from math import gcd
        for entry in json.loads(public_manifest.read_text())['files']:
            wave, rate = sf.read(public_manifest.parent/entry['file'],dtype='float32')
            if wave.ndim>1:
                wave = wave.mean(axis=1)
            factor = gcd(rate,16000)
            wave = resample_poly(wave,16000//factor,rate//factor).astype(np.float32)
            if len(wave)<3200:
                wave = np.pad(wave,(0,3200-len(wave)))
            start = (len(wave)-3200)//2
            adc = np.clip(np.rint(wave[start:start+3200]*2048+2048),0,4095).astype(np.uint16)
            x = (adc.astype(np.float32)-adc.astype(np.float32).mean())/2048
            signals.append(x)
            public_count += 1
    max_frontend = max_network = max_end_to_end = 0.0
    for signal in signals:
        x = np.ascontiguousarray(signal, np.float32)
        got = np.empty((1,64,21), np.float32)
        lib.pulsevad_frontend(x, got)
        parallel_got = np.empty_like(got)
        parallel_lib.pulsevad_frontend(x, parallel_got)
        assert np.array_equal(got,parallel_got), 'Concurrent frontend changed features'
        ref = reference.extract_log_mel_np(x)
        error = float(np.max(np.abs(ref-got)))
        max_frontend = max(max_frontend, error)
        assert np.isfinite(got).all() and error < .015, error
        embedding, logits = np.empty(8,np.float32), np.empty(2,np.float32)
        lib.pulsevad_predict(got, embedding, logits)
        expected = session.run(None, {'log_mel': got})[0][0]
        network_error = float(np.max(np.abs(logits-expected)))
        max_network = max(max_network, network_error)
        assert network_error < 2e-4, network_error
        reference_logits = session.run(None, {'log_mel': ref})[0][0]
        max_end_to_end = max(max_end_to_end, float(np.max(np.abs(logits-reference_logits))))
        assert np.max(np.abs(logits-reference_logits))<.002, (logits,reference_logits)
        assert logits.argmax()==reference_logits.argmax(), (logits,reference_logits)
    # Exercise ADC DC removal and repeatability through the exact deployed API.
    adc = np.full(3200,2048,np.uint16)
    embedding = np.empty(8,np.float32)
    p = lib.pulsevad_process_adc(adc, embedding)
    assert np.isfinite(p) and 0<=p<=1
    assert p == lib.pulsevad_process_adc(adc, embedding)
    head_error = None
    if hasattr(lib,'talking_head_probability'):
        lib.talking_head_probability.argtypes = [F32]
        lib.talking_head_probability.restype = ctypes.c_float
        folder = ROOT/'ml/candidates/talking_head'
        head = json.loads((folder/'head.json').read_text())
        data = np.load(folder/'features.npz')
        head_error = 0.0
        for split in ['train','validation','test']:
            for x in data[f'{split}_x']:
                expected = 1/(1+np.exp(-np.dot(x,head['weights'])-head['bias']))
                got = lib.talking_head_probability(np.ascontiguousarray(x,np.float32))
                head_error = max(head_error,abs(float(expected)-got))
        assert head_error<1e-5, head_error
        class Detector(ctypes.Structure):
            _fields_=[('positive_blocks',ctypes.c_uint),('weak_blocks',ctypes.c_uint),('active',ctypes.c_uint)]
        lib.talking_detector_step.argtypes = [ctypes.POINTER(Detector),ctypes.c_uint,
                                             ctypes.c_float,ctypes.c_uint,ctypes.c_int]
        lib.talking_detector_step.restype = ctypes.c_int
        state = Detector()
        def step(votes=3,rms=20,clipped=0,fault=0):
            return lib.talking_detector_step(ctypes.byref(state),votes,rms,clipped,fault)
        def reset():
            assert (state.positive_blocks,state.weak_blocks,state.active)==(0,0,0)
        assert step()==1 and state.positive_blocks==1  # No one-block alert.
        assert step(votes=0)==0
        reset()
        assert step()==1 and step()==2
        assert step(votes=1)==2 and state.weak_blocks==1  # Bridge a confidence dip.
        assert step()==2 and state.weak_blocks==0  # Strong evidence resumes immediately.
        assert step(votes=0)==2 and step(votes=0)==0  # Bounded release.
        reset()
        assert step()==1 and step()==2 and step(clipped=80)==4
        reset()
        assert step()==1 and step()==2 and step(fault=1)==5
        reset()
        assert step()==1 and step()==2 and step(rms=3.9)==3
        reset()
        assert step(rms=float('nan'))==6
        reset()
        assert step(votes=4)==6
    report = dict(signals=len(signals), public_audio_contexts=public_count,
                  frontend_implementation='Q24 stage-scaled FFT, Q30 twiddles, FP32 mel/normalisation',
                  max_frontend_absolute_error=max_frontend,
                  max_network_logit_error=max_network, max_end_to_end_logit_error=max_end_to_end,
                  upstream_classification_disagreements=0,
                  concurrent_frontend_bit_exact=True,
                  max_own_head_probability_error=head_error,
                  silence_raw_probability=p, notes='Numerical parity only, not classroom accuracy or board timing.')
    (BUILD/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
