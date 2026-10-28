"""Capture an eight-second raw microphone diagnostic and replay the same audio.

Requires audio_talking timing-v4. Writes local WAV/raw ADC/report files, trains
nothing, and returns the board to normal VAD output when finished or cancelled.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT/'firmware/audio/pulsevad/vendor'


class RawParser:
    def __init__(self):
        self.packet = None
        self.discarded = 0
        self.errors = Counter()
        self.last_error = None

    def feed(self, line):
        fields = line.strip().split(',')
        kind = fields[0]
        if kind not in ['RAW_BEGIN','RAW_DATA','RAW_END']:
            return None
        try:
            if kind == 'RAW_BEGIN':
                if self.packet is not None:
                    self.discarded += 1
                self.packet = None
                if len(fields)!=7 or fields[3:5]!=['8000','16000']:
                    raise ValueError('Unsupported raw header')
                window, delivered = int(fields[1]),int(fields[2])
                pulse,own = float(fields[5]),float(fields[6])
                no_model = pulse == -1 and own == -1
                if not 0<=window<2**32 or delivered<0 or (not no_model and (not 0<=pulse<=1 or not 0<=own<=1)):
                    raise ValueError('Invalid raw metadata')
                self.packet = dict(window=window,delivered_us=delivered,
                                   board_pulse=None if no_model else pulse,
                                   board_own=None if no_model else own,samples=[])
                return None
            p = self.packet
            if p is None:
                return None
            if int(fields[1])!=p['window']:
                raise ValueError('Raw window mismatch')
            if kind=='RAW_DATA':
                if len(fields)!=4 or int(fields[2])!=len(p['samples']):
                    raise ValueError('Missing or duplicate raw samples')
                text = fields[3]
                expected = min(128,8000-len(p['samples']))
                if expected<=0 or len(text)!=expected*3 or any(c not in '0123456789abcdef' for c in text):
                    raise ValueError('Invalid raw sample encoding')
                p['samples'].extend(int(text[i:i+3],16) for i in range(0,len(text),3))
            else:
                if len(fields)!=3 or len(p['samples'])!=8000 or int(fields[2])!=sum(p['samples']):
                    raise ValueError('Incomplete/corrupt raw block')
                self.packet = None
                return p
        except (ValueError,IndexError) as error:
            self.packet = None
            self.discarded += 1
            self.last_error = str(error)
            self.errors[self.last_error] += 1
        return None


class LineBuffer:
    """USB CDC is a byte stream; retain partial lines across bulk reads."""
    def __init__(self):
        self.pending = bytearray()
        self.oversized = 0

    def feed(self, data):
        self.pending.extend(data)
        lines = self.pending.split(b'\n')
        self.pending = bytearray(lines.pop())
        for line in lines:
            if len(line)>4096:
                self.oversized += 1
                continue
            yield line.decode('ascii',errors='replace').strip()
        if len(self.pending)>4096:
            self.pending.clear()
            self.oversized += 1


def save_recording(packets, dest, discarded=0):
    """Recording only: no model imports or vendor/model files required."""
    import soundfile as sf
    dest.mkdir(parents=True,exist_ok=True)
    adc = np.asarray([p['samples'] for p in packets],np.uint16)
    np.savez_compressed(dest/'raw_adc.npz',samples=adc,
                        window=np.array([p['window'] for p in packets]),
                        delivered_us=np.array([p['delivered_us'] for p in packets]))
    wave = (adc.astype(np.float32)-adc.mean(axis=1,keepdims=True))/2048
    sf.write(dest/'microphone.wav',wave.reshape(-1),16000,subtype='PCM_16')
    peak = max(float(np.max(np.abs(wave))),1e-6)
    sf.write(dest/'microphone_listen_amplified.wav',wave.reshape(-1)*(.9/peak),16000,subtype='PCM_16')
    metadata=dict(blocks=len(packets),discarded_packets=discarded,
        packets=[{k:v for k,v in p.items() if k!='samples'} for p in packets],
        notes=['Raw ADC samples are unfiltered; WAV subtracts DC per block.',
               'Listening copy is peak-amplified, which also makes existing noise louder.',
               'ADC-only firmware intentionally has gaps between blocks; WAV concatenates the blocks.'])
    (dest/'capture_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return adc


def analyse(packets, dest, discarded=0):
    adc=save_recording(packets,dest,discarded)
    import onnx
    import onnxruntime as ort
    spec = importlib.util.spec_from_file_location('pv_reference',VENDOR/'frontend_np.py')
    frontend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frontend)
    frontend._MEL_FB = np.load(VENDOR/'mel_filterbank.npy')
    model = onnx.load(VENDOR/'pulsevad_2.1k.onnx')
    model.graph.output.append(onnx.helper.make_tensor_value_info(
        '/ReduceMean_output_0',onnx.TensorProto.FLOAT,['batch',8]))
    session = ort.InferenceSession(model.SerializeToString(),providers=['CPUExecutionProvider'])
    head = json.loads((ROOT/'ml/candidates/talking_head/head.json').read_text())
    rows = []
    for index,(p,samples) in enumerate(zip(packets,adc)):
        first = samples[:3200].astype(np.float32)
        x = (first-first.mean())/2048
        logits,embedding = session.run(None,{'log_mel':frontend.extract_log_mel_np(x)})
        pulse = float(1/(1+np.exp(np.clip(logits[0,0]-logits[0,1],-80,80))))
        own = float(1/(1+np.exp(np.clip(-np.dot(embedding[0],head['weights'])-head['bias'],-80,80))))
        centered = samples.astype(np.float64)-samples.mean()
        spectrum = np.abs(np.fft.rfft(centered*np.hanning(8000)))**2
        freq = np.fft.rfftfreq(8000,1/16000)
        spectrum[freq<30]=0
        total = max(float(spectrum.sum()),1e-30)
        rows.append(dict(window=p['window'],index=index,
            instructed_phase='quiet' if index<4 else 'talking',
            rms_adc=float(np.sqrt(np.mean(centered**2))),adc_min=int(samples.min()),
            adc_max=int(samples.max()),adc_mean=float(samples.mean()),
            near_rail_samples=int(np.sum((samples<=4)|(samples>=4091))),
            dominant_hz=float(freq[spectrum.argmax()]),
            power_above_3400_fraction=float(spectrum[freq>3400].sum()/total),
            board_pulse=p['board_pulse'],pc_pulse=pulse,
            board_own=p['board_own'],pc_own=own,
            pulse_difference=abs(p['board_pulse']-pulse) if p['board_pulse'] is not None else None,
            own_difference=abs(p['board_own']-own) if p['board_own'] is not None else None))
    with (dest/'scores.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    summary = {}
    for phase,selection in [('quiet',rows[1:4]),('talking',rows[6:])]:
        if selection:
            summary[phase] = dict(blocks=len(selection),
                mean_rms_adc=float(np.mean([r['rms_adc'] for r in selection])),
                mean_pulse=float(np.mean([r['board_pulse'] for r in selection])) if selection[0]['board_pulse'] is not None else None,
                mean_own=float(np.mean([r['board_own'] for r in selection])) if selection[0]['board_own'] is not None else None)
    consecutive = all(b['window']==a['window']+1 and
                      250000<=b['delivered_us']-a['delivered_us']<=750000
                      for a,b in zip(packets,packets[1:]))
    report = dict(blocks=len(packets),discarded_packets=discarded,
        complete_capture=len(packets)==16 and discarded==0 and consecutive,
        max_board_pc_pulse_difference=max((r['pulse_difference'] for r in rows if r['pulse_difference'] is not None),default=None),
        max_board_pc_own_difference=max((r['own_difference'] for r in rows if r['own_difference'] is not None),default=None),
        instructed_phase_summary=summary,
        notes=['First 2 s instructed quiet, remaining 6 s instructed talking; not verified labels.',
               'Board/PC comparison uses exactly the FIRST 3200 samples of each block.',
               'WAV is for listening; raw ADC and block boundaries are preserved separately.',
               'No accuracy estimate or model training is performed.'])
    (dest/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    print('Saved diagnostic:',dest)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',default='COM5')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--from-npz',type=Path,help='Reanalyse a previous capture without hardware')
    parser.add_argument('--record-only',action='store_true',help='Save WAV/ADC without loading any ML model files')
    args = parser.parse_args()
    dest = args.output or ROOT/'ml/diagnostics/microphone'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')
    if dest.exists():
        parser.error('Output folder already exists; choose a new --output folder')
    if args.from_npz:
        saved=np.load(args.from_npz)
        scores_path=args.from_npz.parent/'scores.csv'
        if scores_path.exists():
            with scores_path.open(newline='') as stream:
                scores=list(csv.DictReader(stream))
        else:
            scores=json.loads((args.from_npz.parent/'capture_metadata.json').read_text())['packets']
        def score(value): return float(value) if value not in [None,''] else None
        packets=[dict(samples=s.tolist(),window=int(w),delivered_us=int(t),
                      board_pulse=score(row['board_pulse']),board_own=score(row['board_own']))
                 for s,w,t,row in zip(saved['samples'],saved['window'],saved['delivered_us'],scores)]
        if not packets:
            parser.error('No saved raw packets')
        if args.record_only: save_recording(packets,dest)
        else: analyse(packets,dest)
        return
    import serial
    decoder=RawParser()
    line_buffer=LineBuffer()
    packets=[]
    counts=Counter()
    bytes_received=0
    ready=False
    recent_headers=[]
    started=time.monotonic()
    print('Close miniterm/Serial Monitor first. Keep the microphone still.')
    print('Connecting: waiting for the Pico to acknowledge raw capture...',flush=True)
    try:
        with serial.Serial(args.port,115200,timeout=.25,write_timeout=1) as ser:
            if hasattr(ser,'set_buffer_size'):
                try:
                    ser.set_buffer_size(rx_size=262144)
                except (OSError,NotImplementedError):
                    pass
            ser.reset_input_buffer()
            ser.write(b'r')
            started=time.monotonic()
            next_status=started+1
            finished=False
            try:
                while time.monotonic()-started<20 and not finished:
                    # readline() performs a Windows serial read per byte. Raw
                    # data needs ~50 KB/s, so drain available data in batches.
                    payload=ser.read(min(max(ser.in_waiting,1),8192))
                    bytes_received += len(payload)
                    for line in line_buffer.feed(payload):
                        kind=line.split(',',1)[0]
                        counts[kind] += 1
                        if kind=='RAW_BEGIN' and len(recent_headers)<2:
                            recent_headers.append(line)
                        if line=='RAW_READY,16':
                            ready=True
                            print('Capturing: QUIET now (waiting for block 1/16).',flush=True)
                        if line=='RAW_DONE' and ready:
                            finished=True
                            break
                        packet=decoder.feed(line)
                        if packet:
                            packets.append(packet)
                            print(f'Audio received: {len(packets)}/16 blocks.',flush=True)
                            if len(packets)==4:
                                print('TALK NOW: repeat a short sentence normally for 6 seconds.',flush=True)
                            if len(packets)==16:
                                finished=True
                                break
                    now=time.monotonic()
                    if now>=next_status and not finished:
                        print(f"Waiting: {len(packets)}/16 valid blocks; "
                              f"{bytes_received} bytes, {counts['RAW_BEGIN']} headers, "
                              f"{counts['RAW_DATA']} chunks, {decoder.discarded} corrupt blocks."
                              + (f' Last error: {decoder.last_error}' if decoder.last_error else ''),flush=True)
                        next_status=now+1
                    if not ready and time.monotonic()-started>5:
                        raise RuntimeError('No RAW_READY response. Requires audio_talking timing-v4 or audio_record_only firmware.')
            finally:
                try:
                    ser.write(b'v')
                except (serial.SerialException,OSError):
                    pass
    except KeyboardInterrupt:
        print('Capture cancelled; returning to VAD.')
    except (serial.SerialException,RuntimeError,OSError) as error:
        print('Diagnostic stopped:',error)
        if not packets:
            raise SystemExit(1) from error
    finally:
        dest.mkdir(parents=True,exist_ok=True)
        transport=dict(raw_ready=ready,bytes_received=bytes_received,
                       lines=dict(counts),valid_blocks=len(packets),discarded_blocks=decoder.discarded,
                       parser_errors=dict(decoder.errors),first_headers=recent_headers,
                       oversized_lines=line_buffer.oversized,elapsed_seconds=time.monotonic()-started)
        (dest/'transport_report.json').write_text(json.dumps(transport,indent=2)+'\n')
        print('Transport report:',dest/'transport_report.json',flush=True)
    if packets:
        if args.record_only:
            save_recording(packets,dest,decoder.discarded)
            print(f'Saved {len(packets)} raw blocks and WAV files to {dest}. No ML models loaded.')
            return
        print('Capture finished. Saving audio and comparing Pico/PC scores...',flush=True)
        report=analyse(packets,dest,decoder.discarded)
        if not report['complete_capture']:
            print('Capture was incomplete; preserved available audio and metadata.')
    else:
        raise SystemExit('No complete raw blocks received. Transport details were saved above.')


if __name__=='__main__':
    main()
