"""Show live Pico speech decisions AND save the same ADC windows to a WAV.

Requires audio_talking timing-v6. Ctrl+C closes the WAV and releases COM5.
Only NumPy and pyserial are needed; inference stays on the board.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import wave

import numpy as np

ROOT=Path(__file__).resolve().parents[2]


class StreamParser:
    def __init__(self):
        self.buffer=bytearray()
        self.packet=None
        self.payload=None
        self.errors=0

    def feed(self,data):
        self.buffer.extend(data)
        while True:
            if self.packet is not None and self.payload is None:
                if len(self.buffer)<12000:
                    break
                self.payload=bytes(self.buffer[:12000])
                del self.buffer[:12000]
            newline=self.buffer.find(b'\n')
            if newline<0:
                if len(self.buffer)>65536:
                    self.buffer.clear();self.packet=None;self.payload=None;self.errors+=1
                break
            raw=bytes(self.buffer[:newline]);del self.buffer[:newline+1]
            line=raw.decode('ascii',errors='replace').strip()
            if not line:
                continue
            if self.packet is not None:
                packet=self.packet;payload=self.payload
                self.packet=None;self.payload=None
                if line!=f"PCM_END,{packet['window']}":
                    self.errors+=1
                    # A newly encountered valid header can resynchronise below.
                else:
                    packed=np.frombuffer(payload,dtype=np.uint8).reshape(-1,3).astype(np.uint16)
                    samples=np.empty(8000,np.uint16)
                    samples[::2]=packed[:,0]|((packed[:,1]&15)<<8)
                    samples[1::2]=(packed[:,1]>>4)|(packed[:,2]<<4)
                    if int(samples.sum(dtype=np.uint32))!=packet['checksum']:
                        self.errors+=1
                    else:
                        packet['samples']=samples
                        yield 'audio',packet
                    continue
            if line.startswith('PCM_BEGIN,'):
                try:
                    fields=line.split(',')
                    if len(fields)!=8 or fields[1]!='1' or fields[4:7]!=['8000','16000','12000']:
                        raise ValueError
                    window,delivered,checksum=int(fields[2]),int(fields[3]),int(fields[7])
                    if not 0<=window<2**32 or delivered<0 or not 0<=checksum<=8000*4095:
                        raise ValueError
                    self.packet=dict(window=window,delivered_us=delivered,checksum=checksum)
                except ValueError:
                    self.errors+=1
            else:
                yield 'line',line


def run_session(ser,folder,seconds=None):
    decoder=StreamParser()
    ready=False
    blocks=missing=0
    first_window=last_window=last_delivery=None
    started=time.monotonic()
    wav_path=folder/'microphone.wav'
    print('WAV:',wav_path,flush=True)
    print('Live speech detection and audio recording. Press Ctrl+C to stop.',flush=True)
    folder.mkdir(parents=True,exist_ok=False)
    with wav_path.open('xb') as raw_file, wave.open(raw_file,'wb') as wav, \
            (folder/'events.jsonl').open('x',encoding='utf-8') as events, \
            (folder/'audio_windows.jsonl').open('x',encoding='utf-8') as windows:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        try:
            ser.reset_input_buffer()
            ser.write(b's')
            while seconds is None or time.monotonic()-started<seconds:
                payload=ser.read(min(max(ser.in_waiting,1),8192))
                for kind,item in decoder.feed(payload):
                    if kind=='line':
                        if item=='STREAM_READY,1':
                            ready=True
                            print('Recording started.',flush=True)
                        elif item.startswith('VAD,'):
                            print(item,flush=True)
                            fields=dict(field.split('=',1) for field in item.split(',')[1:] if '=' in field)
                            if ready:
                                fields['host_received_utc']=datetime.now(timezone.utc).isoformat()
                                events.write(json.dumps(fields)+'\n');events.flush()
                    else:
                        if not ready:
                            continue
                        window=item['window']
                        if last_window is not None and window<=last_window:
                            decoder.errors+=1
                            continue
                        if first_window is None:
                            first_window=window
                        gap=window-last_window-1 if last_window is not None else 0
                        if gap>120:
                            raise RuntimeError('Window sequence jumped; board may have restarted.')
                        if gap:
                            wav.writeframes(b'\0'*(gap*8000*2));missing+=gap
                            print(f'Audio gap: inserted silence for {gap} missing blocks.',flush=True)
                        # Fixed midpoint conversion preserves every ADC bit
                        # and introduces no block-wise gain/DC discontinuity.
                        pcm=((item['samples'].astype(np.int32)-2048)*16).astype('<i2')
                        start_sample=wav.getnframes()
                        wav.writeframes(pcm.tobytes())
                        interval=item['delivered_us']-last_delivery if last_delivery is not None else None
                        metadata=dict(window=window,delivered_us=item['delivered_us'],
                            wav_start_sample=start_sample,wav_start_seconds=start_sample/16000,
                            samples=8000,missing_blocks_before=gap,delivery_interval_us=interval,
                            timing_discontinuity=interval is not None and not 250000<=interval<=750000)
                        windows.write(json.dumps(metadata)+'\n');windows.flush()
                        blocks+=1;last_window=window;last_delivery=item['delivered_us']
                if not ready and time.monotonic()-started>5:
                    raise RuntimeError('No STREAM_READY response. Flash the updated audio_talking timing-v6 firmware.')
        except KeyboardInterrupt:
            print('\nRecording stopped.',flush=True)
        finally:
            try: ser.write(b'v')
            except OSError: pass
            report=dict(received_blocks=blocks,missing_blocks_filled_with_silence=missing,
                invalid_packets=decoder.errors,incomplete_packet=decoder.packet is not None,
                wav_samples=wav.getnframes(),wav_seconds=wav.getnframes()/16000,
                first_window=first_window,last_window=last_window,
                notes=['Audio is the exact ADC window used for each matching WINDOW speech decision.',
                       'WAV uses (ADC-2048)*16: lossless fixed scaling to PCM16, no filtering or peak amplification.',
                       'Missing window IDs are filled with silence, never silently removed.',
                       'Delivery timestamps are not sample-start timestamps; inspect timing flags and OVERRUN.',
                       'Interrupted/corrupt final packets are excluded. No inference is performed on the PC.'])
            (folder/'recording_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Saved {blocks} audio blocks ({report["wav_seconds"]:.1f}s): {wav_path}',flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='COM5')
    parser.add_argument('--output',type=Path,help='New session directory; must not already exist')
    parser.add_argument('--seconds',type=float,help='Optional wall-clock duration; otherwise Ctrl+C stops')
    args=parser.parse_args()
    if args.seconds is not None and args.seconds<=0:
        parser.error('--seconds must be positive')
    folder=args.output or ROOT/'ml/diagnostics/speech_sessions'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    if folder.exists():parser.error('Output directory already exists')
    import serial
    try:
        with serial.Serial(args.port,115200,timeout=.25,write_timeout=1) as ser:
            if hasattr(ser,'set_buffer_size'):
                try: ser.set_buffer_size(rx_size=262144)
                except (OSError,NotImplementedError): pass
            run_session(ser,folder,args.seconds)
    except (serial.SerialException,OSError,RuntimeError) as error:
        raise SystemExit(f'Monitor stopped: {error}') from error


if __name__=='__main__':
    main()
