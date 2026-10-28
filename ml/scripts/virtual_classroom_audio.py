"""Audio-based virtual nodes: exact deployed C VAD, policy and comparison.

Waveform mixing is a controlled approximation, not a classroom acoustics model.
Default public speech consists of digits, not actual lectures/conversations.
"""
from collections import deque
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import wave

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from reference_nodes import ROOT, NativeService, pair_command

SAMPLE_RATE = 16000
WINDOW = 8000
DATA = ROOT / 'ml/data/vad_public'


class Quality(ctypes.Structure):
    _fields_ = [('minimum', ctypes.c_uint16), ('maximum', ctypes.c_uint16),
               ('mean_q8', ctypes.c_uint32), ('ac_rms_q8', ctypes.c_uint32),
               ('clipped_samples', ctypes.c_uint32)]


class SpeechState(ctypes.Structure):
    _fields_ = [('positive_blocks', ctypes.c_uint), ('weak_blocks', ctypes.c_uint),
               ('active', ctypes.c_uint)]


class NativeAudioModel:
    """Use the same three contexts, ADC quality and speech policy as the Pico."""
    def __init__(self):
        gcc = shutil.which('gcc') or ('C:/msys64/ucrt64/bin/gcc.exe' if Path('C:/msys64/ucrt64/bin/gcc.exe').exists() else None)
        if not gcc:raise RuntimeError('Host GCC is required for the audio environment')
        base = ROOT / 'firmware/audio'
        build = ROOT / 'firmware/build/virtual_audio'
        build.mkdir(parents=True, exist_ok=True)
        target = build / f'vad_{os.getpid()}.dll'
        subprocess.run([gcc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-Wno-array-parameter', '-shared', str(base/'pulsevad/pulsevad.c'),
            str(base/'pulsevad/talking_detector.c'), str(base/'audio_signal_quality.c'),
            '-lm', '-o', str(target)], check=True)
        if os.name == 'nt':self.dll_path = os.add_dll_directory(str(Path(gcc).parent))
        self.lib = ctypes.CDLL(str(target))
        u16 = np.ctypeslib.ndpointer(dtype=np.uint16, flags='C_CONTIGUOUS')
        f32 = np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS')
        self.lib.pulsevad_process_adc.argtypes = [u16, f32]
        self.lib.pulsevad_process_adc.restype = ctypes.c_float
        self.lib.talking_head_probability.argtypes = [f32]
        self.lib.talking_head_probability.restype = ctypes.c_float
        self.lib.audio_signal_quality.argtypes = [u16, ctypes.c_size_t, ctypes.POINTER(Quality)]
        self.lib.talking_detector_step.argtypes = [ctypes.POINTER(SpeechState), ctypes.c_uint,
                                                 ctypes.c_float, ctypes.c_uint, ctypes.c_int]
        self.lib.talking_event_name.argtypes = [ctypes.c_int]
        self.lib.talking_event_name.restype = ctypes.c_char_p
        self.own_head = bool(self.lib.talking_uses_own_head())
        self.lib.pulsevad_init()

    def evaluate(self, adc, state, time_us):
        adc = np.ascontiguousarray(adc, dtype=np.uint16)
        if adc.shape != (WINDOW,) or adc.max() > 4095:
            raise ValueError('Expected one unsigned 12-bit, 8000-sample ADC block')
        quality = Quality()
        if not self.lib.audio_signal_quality(adc, WINDOW, ctypes.byref(quality)):
            raise ValueError('Invalid audio block')
        pulse, own = [], []
        for offset in (0, 2400, 4800):
            embedding = np.empty(8, dtype=np.float32)
            pulse.append(float(self.lib.pulsevad_process_adc(adc[offset:offset+3200], embedding)))
            own.append(float(self.lib.talking_head_probability(embedding)))
        scores = own if self.own_head else pulse
        votes = sum(p >= .5 for p in scores)
        rms = quality.ac_rms_q8 / 256
        event = self.lib.talking_detector_step(ctypes.byref(state), votes, rms, quality.clipped_samples, 0)
        return dict(time_us=time_us, rms=rms, votes=votes, valid=quality.clipped_samples < 80,
                    pulse_prob=float(np.mean(pulse)), own_prob=float(np.mean(own)),
                    context_scores=scores, event=self.lib.talking_event_name(event).decode('ascii'),
                    clipped_samples=int(quality.clipped_samples), model='OWN_TRAINED_HEAD' if self.own_head else 'PRETRAINED_PULSEVAD')


def read_wave(path):
    data, rate = sf.read(path, dtype='float32', always_2d=True)
    data = data.mean(axis=1)
    if not len(data) or not np.isfinite(data).all():raise ValueError(f'Empty or invalid audio: {path}')
    factor = math.gcd(int(rate), SAMPLE_RATE)
    if rate != SAMPLE_RATE:data = resample_poly(data, SAMPLE_RATE//factor, int(rate)//factor)
    return np.asarray(data-data.mean(), np.float32)


class AudioLoop:
    def __init__(self, samples, label, sources):
        samples = np.asarray(samples, np.float32)
        rms = float(np.sqrt(np.mean(samples.astype(np.float64)**2)))
        if not np.isfinite(rms) or rms < 1e-8:raise ValueError('Audio must contain a non-silent waveform')
        self.samples = samples / rms  # ONE file-level gain, never per-window normalisation.
        self.label, self.sources, self.position = label, sources, 0
        if len(samples) < WINDOW:
            self.samples = np.tile(self.samples, math.ceil(WINDOW/len(samples)))
        energy = np.r_[0., np.cumsum(self.samples.astype(np.float64)**2)]
        start = int(np.argmax(energy[WINDOW:] - energy[:-WINDOW]))
        self.excerpt = self.samples[start:start+WINDOW].copy()

    @classmethod
    def from_file(cls, path):
        path = Path(path).resolve()
        return cls(read_wave(path), path.name, [dict(file=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())])

    def read(self):
        indexes = (np.arange(WINDOW)+self.position) % len(self.samples)
        self.position = (self.position+WINDOW) % len(self.samples)
        return self.samples[indexes]


def default_audio():
    if not (DATA/'manifest.json').exists():
        raise RuntimeError('Public demo audio is missing. Run ml/scripts/fetch_vad_audio.py first.')
    entries = json.loads((DATA/'manifest.json').read_text())['files']
    def speech(speaker):
        rows = [e for e in entries if e['source']==f'fsdd:{speaker}' and e['file'].endswith('_5.wav')]
        if not rows:raise RuntimeError(f'Missing default speech: {speaker}')
        samples = []
        for entry in rows:
            samples.extend([read_wave(DATA/entry['file']), np.zeros(640, np.float32)])
        return AudioLoop(np.concatenate(samples), f'Speech proxy: FSDD {speaker} digits', rows)
    noises = {}
    cough_manifest = DATA/'virtual_audio/manifest.json'
    if cough_manifest.exists():
        for i, entry in enumerate(json.loads(cough_manifest.read_text())):
            noises[f'Cough {i+1}'] = AudioLoop(read_wave(DATA/entry['file']), f'ESC-50 cough {i+1}', [entry])
    for category, label in [('door_wood_knock', 'Wood knock'), ('rain', 'Rain')]:
        entry = next(e for e in entries if e.get('category')==category and e['split']=='test')
        noises[label] = AudioLoop(read_wave(DATA/entry['file']), f'ESC-50 {category}', [entry])
    return speech('george'), speech('lucas'), noises


class AudioClassroom:
    """Two virtual microphones fed waveforms, with no hand-assigned speech votes."""
    def __init__(self):
        self.model = NativeAudioModel()
        self.service = NativeService()
        self.lecturer, self.student, self.noises = default_audio()
        self.noise_name = next(iter(self.noises))
        self.time_us = 0
        self.history = deque(maxlen=40)
        self.restart()

    def restart(self):
        self.service.send('@RESET\n')
        self.ready, self.calibration_pairs, self.calibration_ticks = False, 0, 0
        self.reference_state, self.student_state = SpeechState(), SpeechState()
        self.rng = np.random.default_rng(904)
        for stream in [self.lecturer, self.student, *self.noises.values()]:stream.position = 0
        self.history.clear()

    def load(self, role, path):
        stream = AudioLoop.from_file(path)
        if role == 'noise':
            self.noises['Custom WAV'] = stream
            self.noise_name = 'Custom WAV'
        elif role in ('lecturer', 'student'):
            setattr(self, role, stream)
        else:raise ValueError('Unknown audio role')
        self.restart()  # New source => recalibrate, do not reuse a stale baseline.

    def step(self, lecturer=150, lecturer_speech=True, student=0,
             student_speech=False, noise=0, reference_valid=True, burst=False, noise_burst=False):
        self.time_us += 500000
        calibrating = not self.ready
        if calibrating:
            lecturer = 100 + (self.calibration_ticks % 7)*35
            self.calibration_ticks += 1
            lecturer_speech, student_speech, reference_valid = True, False, True
            student, noise = 0, 0
        if burst and not calibrating:student, student_speech = 200, True
        if noise_burst and not calibrating:noise = 200
        lecture_wave = self.lecturer.read() * (lecturer if lecturer_speech else 0)
        student_wave = self.student.read() * (student if student_speech else 0)
        noise_stream = self.noises[self.noise_name]
        noise_wave = (noise_stream.excerpt.copy() if noise_burst else noise_stream.read()) * noise
        ref_wave = lecture_wave + self.rng.normal(0, 2, WINDOW)
        local_wave = .2*lecture_wave + student_wave + noise_wave + self.rng.normal(0, 2, WINDOW)
        def adc(data):return np.ascontiguousarray(np.clip(np.rint(data+2048), 0, 4095), np.uint16)
        reference_adc, student_adc = adc(ref_wave), adc(local_wave)
        ref = self.model.evaluate(reference_adc, self.reference_state, self.time_us)
        local = self.model.evaluate(student_adc, self.student_state, self.time_us)
        ref['valid'] = ref['valid'] and bool(reference_valid)
        line, = self.service.send(pair_command(1, self.time_us, ref, local))
        result = dict(part.split('=', 1) for part in line.split(',')[1:])
        self.calibration_pairs = int(result['CAL_PAIRS'])
        if result['DECISION'] == 'BASELINE_READY':self.ready = True
        record = dict(time_us=self.time_us, reference=ref, student=local, result=result,
                      calibrating=calibrating, noise_burst=bool(noise_burst and not calibrating),
                      audio_based=True, sources=dict(lecturer=self.lecturer.label, student=self.student.label,
                                                   noise=noise_stream.label))
        self.history.append((reference_adc, student_adc, record))
        return record

    def save_audio(self, folder):
        if not self.history:raise ValueError('No audio windows available yet')
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=False)
        for name, index in [('reference', 0), ('student', 1)]:
            adc = np.concatenate([frame[index] for frame in self.history])
            pcm = ((adc.astype(np.int32)-2048)*16).astype('<i2')
            with wave.open(str(folder/f'{name}.wav'), 'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(SAMPLE_RATE)
                output.writeframes(pcm.tobytes())
        provenance = dict(lecturer=self.lecturer.sources, student=self.student.sources,
                          noises={name: stream.sources for name, stream in self.noises.items()})
        (folder/'windows.json').write_text(json.dumps(dict(windows=[r for _, _, r in self.history],
            provenance=provenance, notes='Controlled waveform mixture, not a real room or accuracy estimate.'), indent=2)+'\n')
        return folder/'student.wav'


def verify_audio():
    """Measure real outputs; do not assert that every cough must be rejected."""
    from datetime import datetime, timezone
    classroom = AudioClassroom()
    folder = ROOT/'ml/diagnostics/virtual_classroom'/datetime.now(timezone.utc).strftime('audio_test_%Y%m%d_%H%M%S_%f_UTC')
    folder.mkdir(parents=True)
    scenarios = [
        ('lecturer_only', dict(lecturer=150), None),
        ('louder_lecturer', dict(lecturer=450), None),
        ('student_joins', dict(lecturer=150, student=140, student_speech=True), None),
        ('coughs_without_lecturer', dict(lecturer_speech=False, noise=200), 'Cough 1'),
        ('coughs_over_lecturer', dict(lecturer=150, noise=200), 'Cough 1'),
        ('second_cough_recording_over_lecturer', dict(lecturer=150, noise=200), 'Cough 2'),
        ('three_separated_cough_excerpts', dict(lecturer=150), 'Cough 1'),
        ('three_consecutive_cough_excerpts', dict(lecturer=150), 'Cough 1'),
        ('rain_over_lecturer', dict(lecturer=150, noise=200), 'Rain'),
        ('knock_over_lecturer', dict(lecturer=150, noise=200), 'Wood knock'),
        ('reference_lost', dict(lecturer=150, reference_valid=False, student=140, student_speech=True), None),
        ('silence', dict(lecturer_speech=False), None),
    ]
    summary = []
    for name, inputs, noise_name in scenarios:
        if noise_name and noise_name not in classroom.noises:
            print('SKIP', name, '(cough demo audio not prepared)')
            summary.append(dict(scenario=name, skipped=True));continue
        if noise_name:classroom.noise_name = noise_name
        classroom.restart()
        for _ in range(160):
            classroom.step()
            if classroom.ready:break
        assert classroom.ready, 'Calibration failed using actual speech votes'
        records = []
        for i in range(20):
            extra = {}
            if name == 'three_separated_cough_excerpts':extra['noise_burst'] = i in (3, 8, 13)
            if name == 'three_consecutive_cough_excerpts':extra['noise_burst'] = i in (3, 4, 5)
            records.append(classroom.step(**inputs, **extra))
        for record in records:
            for node in ('reference', 'student'):
                evidence = record[node]
                assert evidence['votes'] == sum(p >= .5 for p in evidence['context_scores'])
                assert len(evidence['context_scores']) == 3
                assert all(0 <= p <= 1 for p in evidence['context_scores'])
        decisions = [r['result']['DECISION'] for r in records]
        if name in ('lecturer_only', 'louder_lecturer', 'silence'):
            assert 'STUDENT_TALKING' not in decisions, (name, decisions)
        if name == 'student_joins':assert 'STUDENT_TALKING' in decisions
        if name == 'reference_lost':assert set(decisions) == {'UNKNOWN'}
        saved = classroom.save_audio(folder/name)
        with wave.open(str(saved), 'rb') as recording:
            assert recording.getframerate() == SAMPLE_RATE
            pcm = np.frombuffer(recording.readframes(recording.getnframes()), dtype='<i2')
        replay = (pcm.astype(np.int32)//16+2048).astype(np.uint16)
        original = np.concatenate([adc for _, adc, _ in classroom.history])
        assert np.array_equal(replay, original), 'Saved WAV changed classified ADC samples'
        # Run the saved waveform through the model again; scores must match.
        first = classroom.history[0][2]
        got = classroom.model.evaluate(replay[:WINDOW], SpeechState(), first['time_us'])
        assert np.allclose(got['context_scores'], first['student']['context_scores'], atol=1e-7, rtol=0)
        summary.append(dict(scenario=name, test_blocks=len(records),
            speech_positive_blocks=sum(r['student']['votes'] >= 2 for r in records),
            old_local_talking_blocks=sum(r['student']['event'] == 'TALKING' for r in records),
            comparison_alert_blocks=decisions.count('STUDENT_TALKING'),
            audio=str(saved), decisions=decisions))
        print(f"{name}: local TALKING {summary[-1]['old_local_talking_blocks']}/20; "
              f"comparison alert {summary[-1]['comparison_alert_blocks']}/20", flush=True)
    clipped = classroom.model.evaluate(np.full(WINDOW, 4095, np.uint16), SpeechState(), classroom.time_us)
    assert not clipped['valid'] and clipped['event'] == 'CLIPPED'
    quiet = classroom.model.evaluate(np.full(WINDOW, 2048, np.uint16), SpeechState(), classroom.time_us)
    assert quiet['event'] == 'LOW_LEVEL' and quiet['votes'] == 0
    (folder/'report.json').write_text(json.dumps(dict(passed=True, actual_c_model=True,
        model='OWN_TRAINED_HEAD' if classroom.model.own_head else 'PRETRAINED_PULSEVAD', scenarios=summary,
        notes=['Scores come from the deployed C model on waveform mixtures, not assigned speech flags.',
               'Default speech is FSDD digits and noise is ESC-50; these are demonstrations, not classroom accuracy.',
               'Per-case WAV contains calibration followed by the test, up to 20 seconds total.',
               'Cough false positives are retained in the report; no cough rejection guarantee.']), indent=2)+'\n')
    print('PASS: audio-based calibration, deployed model votes, comparison, quality and lossless WAV replay.')
    print('Report and reference/student WAVs:', folder)
