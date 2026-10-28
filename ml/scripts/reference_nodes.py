"""Lecturer-baseline demo/USB bridge. The final decision runs in Pico C code.

--simulate runs that same C command service on the PC, without microphones.
Live mode relays time-aligned readings back to the reference Pico for decisions.
The existing four-class UDP protocol is not changed.
"""
import argparse
from collections import deque
import ctypes
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parents[2]


def pair_command(node,now,ref,student):
    return (f"@PAIR,{node},{now},{ref['time_us']},{ref['rms']:.6f},{ref['votes']},{int(ref['valid'])},"
            f"{student['time_us']},{student['rms']:.6f},{student['votes']},{int(student['valid'])}\n")


class NativeService:
    """Host testing only: compile the actual firmware command service."""
    def __init__(self):
        gcc=shutil.which('gcc') or ('C:/msys64/ucrt64/bin/gcc.exe' if Path('C:/msys64/ucrt64/bin/gcc.exe').exists() else None)
        if not gcc:raise RuntimeError('Host GCC is required for --simulate and verification')
        build=ROOT/'firmware/build/reference_host';build.mkdir(parents=True,exist_ok=True)
        target=build/f'reference_{os.getpid()}.dll'
        base=ROOT/'firmware/audio'
        subprocess.run([gcc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
            str(base/'reference_detector.c'),str(base/'reference_service.c'),
            str(base/'pulsevad/talking_detector.c'),'-lm','-o',str(target)],check=True)
        if os.name=='nt':self.dll_path=os.add_dll_directory(str(Path(gcc).parent))
        self.lib=ctypes.CDLL(str(target))
        self.callback_type=ctypes.CFUNCTYPE(None,ctypes.POINTER(ctypes.c_char),ctypes.c_size_t)
        self.lib.reference_service_feed.argtypes=[ctypes.c_int,self.callback_type]
        self.send('@RESET\n')

    def send(self,command):
        output=[]
        callback=self.callback_type(lambda p,n:output.append(ctypes.string_at(p,n)))
        for c in command.encode('ascii'):self.lib.reference_service_feed(c,callback)
        return b''.join(output).decode('ascii').splitlines()


def simulated_pairs():
    t=1000000
    def packet(rms,votes=3,valid=True):return dict(time_us=t,rms=rms,votes=votes,valid=valid)
    for i in range(20):
        ref=100+(i%7)*35
        yield 'lecturer-only calibration',t,packet(ref),packet(math.sqrt(.04*ref*ref+100))
        t+=500000
    yield 'louder lecturer only',t,packet(600),packet(math.sqrt(.04*600*600+100));t+=500000
    for _ in range(3):
        yield 'one cough-like positive block',t,packet(150),packet(200);t+=500000
        yield 'gap after cough',t,packet(150),packet(math.sqrt(1000),0);t+=500000
    for _ in range(2):
        yield 'loud non-speech',t,packet(150),packet(300,0);t+=500000
    for _ in range(2):
        yield 'additional sustained student speech',t,packet(150),packet(150);t+=500000
    yield 'one weak block during speech',t,packet(150),packet(150,1);t+=500000
    yield 'student speech resumes',t,packet(150),packet(150);t+=500000
    for _ in range(2):
        yield 'student stops',t,packet(150),packet(math.sqrt(1000),0);t+=500000
    yield 'reference invalid',t,packet(150,valid=False),packet(150)


def simulate():
    service=NativeService()
    print('SIMULATED logic check only: these are not recordings or accuracy results.')
    for label,now,ref,student in simulated_pairs():
        for line in service.send(pair_command(1,now,ref,student)):
            print(label,'->',line)


class ClockAligner:
    """Approximate shared clock from receipt minus reported processing latency.

    USB jitter is bounded using the least delayed of recent observations.
    This is a demo bridge, not sample-clock synchronisation or echo cancellation.
    """
    def __init__(self):self.offsets=deque(maxlen=16);self.last_sender=None;self.last_window=None
    def convert(self,fields,received_us):
        sender=int(fields['DELIVERED_US']);window=int(fields['WINDOW'])
        reboot=self.last_sender is not None and (sender<self.last_sender or window<=self.last_window)
        if reboot:self.offsets.clear()
        self.last_sender=sender;self.last_window=window
        work=int(fields.get('WORK_US',fields['PROCESSING_US']))
        if not 0<=work<=2000000:raise ValueError('Invalid processing time')
        self.offsets.append(received_us-work-sender)
        rms=float(fields['RMS_ADC']);votes=int(fields['SPEECH_VOTES'])
        if not math.isfinite(rms) or not 0<=rms<=4095 or not 0<=votes<=3:raise ValueError('Invalid audio fields')
        return dict(time_us=sender+min(self.offsets),rms=rms,votes=votes,
            valid=int(fields.get('OVERRUN','1'))==0 and 0<=int(fields.get('ADC_NEAR_RAIL','8000'))<80
                and fields.get('EVENT') not in ('TIMING_FAULT','INVALID_SIGNAL','CLIPPED'),
            window=window,reboot=reboot,received_us=received_us,build=fields.get('BUILD',''),
            pulse_prob=float(fields['PULSE_PROB']) if 'PULSE_PROB' in fields else None,
            own_prob=float(fields['OWN_PROB']) if 'OWN_PROB' in fields else None,
            event=fields.get('EVENT',''),processing_us=work,
            clipped_samples=int(fields.get('ADC_NEAR_RAIL','8000')))


class SerialWorker(threading.Thread):
    def __init__(self,port,name,incoming,stop):
        super().__init__(daemon=True);self.port=port;self.name=name;self.incoming=incoming;self.stop=stop
        self.outgoing=queue.Queue();self.clock=ClockAligner()
    def send(self,text):self.outgoing.put(text.encode('ascii'))
    def run(self):
        import serial
        try:
            with serial.Serial(self.port,115200,timeout=.1,write_timeout=1) as ser:
                ser.reset_input_buffer();ser.write(b'v')  # Text telemetry; no WAV transport load.
                pending=bytearray()
                while not self.stop.is_set():
                    while not self.outgoing.empty():ser.write(self.outgoing.get_nowait())
                    pending.extend(ser.read(min(max(ser.in_waiting,1),8192)))
                    while b'\n' in pending:
                        raw,_,tail=pending.partition(b'\n');pending=bytearray(tail)
                        line=raw.decode('ascii',errors='replace').strip()
                        if line.startswith('VAD,'):
                            fields=dict(x.split('=',1) for x in line.split(',')[1:] if '=' in x)
                            try:reading=self.clock.convert(fields,time.monotonic_ns()//1000)
                            except (KeyError,ValueError):continue
                            self.incoming.put((self.name,'reading',reading))
                        elif line.startswith(('REF_RESULT,','REF_RESET,','REF_ERROR,')):
                            self.incoming.put((self.name,'result',line))
                    if len(pending)>65536:pending.clear()
                ser.write(b'v')
        except Exception as error:
            self.incoming.put((self.name,'error',str(error)))


def live(reference_port,student_ports,folder,*,stop=None,on_event=None,commands=None,quiet=False):
    if len(set([reference_port]+student_ports))!=1+len(student_ports):
        raise ValueError('Each node must use a different COM port')
    folder.mkdir(parents=True,exist_ok=False)
    incoming=queue.Queue();stop=stop if stop is not None else threading.Event()
    def publish(kind,value):
        if on_event is not None:on_event(kind,value)
    def say(value):
        if not quiet:print(value,flush=True)
    reference=SerialWorker(reference_port,'reference',incoming,stop)
    workers=[reference]+[SerialWorker(p,str(i+1),incoming,stop) for i,p in enumerate(student_ports)]
    refs={str(i+1):deque(maxlen=8) for i in range(len(student_ports))}
    students={node:deque(maxlen=8) for node in refs}
    started=time.monotonic();last_seen={};reset_sent=False;last_unknown=0;reference_verified=False
    say('LECTURER-ONLY CALIBRATION: keep student areas quiet until BASELINE_READY for each node.')
    say('At least 20 valid lecturer-speech pairs per node; no student talking during calibration.')
    say(f'Logs: {folder}')
    publish('session',dict(folder=str(folder),reference_port=reference_port,student_ports=student_ports))
    for worker in workers:worker.start()
    try:
        with (folder/'pairs.jsonl').open('x',encoding='utf-8') as pairs, \
             (folder/'decisions.jsonl').open('x',encoding='utf-8') as results:
            while not stop.is_set():
                if commands is not None:
                    try:requested=commands.get_nowait()
                    except queue.Empty:requested=None
                    if requested=='reset':
                        if reference_verified:
                            reference.send('@RESET\n')
                            for q in list(refs.values())+list(students.values()):q.clear()
                            publish('notice','Recalibration requested. Keep student areas quiet.')
                        else:publish('notice','Waiting for reference firmware before recalibrating.')
                try:name,kind,value=incoming.get(timeout=.2)
                except queue.Empty:name=kind=value=None
                now=time.monotonic_ns()//1000
                if kind=='error':raise RuntimeError(f'{name}: {value}')
                if kind=='result':
                    say(value)
                    publish('result',value)
                    results.write(json.dumps(dict(received_us=now,line=value))+'\n');results.flush()
                if kind=='reading':
                    last_seen[name]=now
                    publish('reading',dict(node=name,reading=value))
                    if name=='reference' and value['build']!='timing-v7':
                        raise RuntimeError('Reference Pico needs the new audio_talking timing-v7 firmware')
                    if name=='reference':reference_verified=True
                    if reference_verified and (not reset_sent or value['reboot']):
                        reference.send('@RESET\n');reset_sent=True
                        for q in list(refs.values())+list(students.values()):q.clear()
                    if name=='reference':
                        for q in refs.values():q.append(value)
                    else:students[name].append(value)
                for node in students:
                    if not reset_sent:continue
                    rq,sq=refs[node],students[node]
                    while rq and sq:
                        r,s=rq[0],sq[0];delta=r['time_us']-s['time_us']
                        if delta < -250000:rq.popleft();continue
                        if delta > 250000:
                            sq.popleft();s=dict(s,valid=False)
                        else:rq.popleft();sq.popleft()
                        reference.send(pair_command(int(node),now,r,s))
                        pairs.write(json.dumps(dict(node=node,now_us=now,reference=r,student=s))+'\n');pairs.flush()
                stale=[n for n in ['reference']+list(students) if n not in last_seen or now-last_seen[n]>1500000]
                if stale and now-last_unknown>1500000:
                    say('UNKNOWN: missing/stale node(s): '+','.join(stale));last_unknown=now
                    publish('stale',stale)
                    # Force persistence reset; stale data must never sustain an alert.
                    for node in students:
                        if 'reference' not in stale and node not in stale:continue
                        dummy=dict(time_us=now,rms=0,votes=0,valid=False)
                        if reset_sent:reference.send(pair_command(int(node),now,dummy,dummy))
                if time.monotonic()-started>8 and not last_seen:
                    raise RuntimeError('No VAD telemetry. Check ports and flash audio_talking on both nodes.')
    except KeyboardInterrupt:
        say('\nStopped reference comparison.')
    finally:
        stop.set()
        for worker in workers:worker.join(timeout=2)
        publish('stopped',None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate',action='store_true')
    parser.add_argument('--reference-port')
    parser.add_argument('--student-port',action='append',default=[])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.simulate:simulate();return
    if not args.reference_port or not 1<=len(args.student_port)<=7:
        parser.error('Provide --reference-port COM5 and 1..7 --student-port COM6 options')
    folder=args.output or ROOT/'ml/diagnostics/reference_sessions'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    try:live(args.reference_port,args.student_port,folder)
    except (OSError,ValueError,RuntimeError) as error:raise SystemExit(str(error)) from error


if __name__=='__main__':main()
