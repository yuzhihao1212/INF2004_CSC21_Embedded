"""Check dashboard state and the real serial-bridge/C-service event flow offline."""
import argparse
import json
import math
from pathlib import Path
import queue
import tempfile
import threading
from unittest.mock import patch

from reference_dashboard import DashboardState
from reference_nodes import ROOT, NativeService, live


def line(decision, count=20, reason='EXCESS_SPEECH', hold=0):
    return (f'REF_RESULT,NODE=1,DECISION={decision},REASON={reason},CAL_PAIRS={count},'
            f'EXPECTED_RMS=30,THRESHOLD_RMS=42,STUDENT_RMS=90,HOLD={hold}')


def reading(rms=100, votes=3, valid=True):
    return dict(rms=rms, votes=votes, valid=valid, build='timing-v7')


def state_checks():
    state = DashboardState()
    state.apply('session', dict(folder='test'), 10)
    assert 'Waiting' in state.banner(10)[0]
    for name in ('reference', '1'):state.apply('reading', dict(node=name, reading=reading()), 10)
    state.apply('result', line('CALIBRATING', count=15, reason='WAITING_FOR_LECTURER_SPEECH'), 10)
    assert state.pairs == 15 and not state.ready
    assert '15 /' in state.banner(10)[0]
    assert 'paused' in state.banner(10)[1]
    assert state.student_history[-1][2:] == (None, None)
    state.apply('result', line('BASELINE_READY', reason='BASELINE_READY'), 10)
    assert state.ready
    state.apply('result', line('STUDENT_TALKING'), 10)
    assert state.banner(10)[0] == 'Possible student talking'
    assert 'Waiting for fresh' in state.banner(12)[0]  # No latched stale alert.
    state.apply('reading', dict(node='1', reading=reading(valid=False)), 10.2)
    assert state.banner(10.2)[0] == 'Student mic: invalid signal'
    clipped = dict(reading(valid=False), event='CLIPPED', clipped_samples=124)
    state.apply('reading', dict(node='1', reading=clipped), 10.21)
    assert state.banner(10.21)[0] == 'Student mic: signal clipping'
    assert '124/8000' in state.banner(10.21)[1]
    # A delayed invalid-pair result still explains the recently clipped block
    # even if the newest node reading has already recovered.
    state.apply('reading', dict(node='1', reading=reading()), 10.3)
    state.apply('result', line('UNKNOWN', reason='INVALID_OR_STALE_INPUT'), 10.31)
    assert 'recent student mic: signal clipping' in state.banner(10.31)[0]
    state.apply('result', line('NO_STUDENT_TALKING', reason='WITHIN_LECTURER_BASELINE'), 10.32)
    assert state.banner(10.32)[0] == 'No additional sustained speech flagged'
    state.request_reset()
    state.apply('result', line('STUDENT_TALKING'), 10.3)
    assert not state.ready and state.result is None  # Ignore pre-reset results.
    state.apply('result', 'REF_RESET,OK', 10.4)
    assert not state.awaiting_reset and state.pairs == 0
    state.apply('error', 'Wrong firmware', 10.5)
    assert state.banner(10.5)[1] == 'Wrong firmware'
    state.apply('stopped', None, 10.6)
    assert not state.running


def bridge_checks():
    """Fake COM readers; pairing, command parsing and decisions are real code."""
    service = NativeService()
    clock = [1_000_000]
    original_queue = queue.Queue
    class TimedQueue(original_queue):
        def get(self, *args, **kwargs):
            item = super().get(*args, **kwargs)
            if isinstance(item, tuple) and len(item)==3 and item[1]=='reading':
                clock[0] = item[2]['received_us']
            return item

    class FakeWorker:
        def __init__(self, port, name, incoming, stop):self.name, self.incoming = name, incoming
        def start(self):
            if self.name != 'reference':return
            self.batch(1_000_000)
        def batch(self, start):
            for i in range(22):
                t = start+i*500_000
                ref = 100+(i%7)*35
                student = math.sqrt(.04*ref**2+100) if i<20 else 180
                for name, rms in [('reference', ref), ('1', student)]:
                    r = dict(time_us=t, received_us=t+470_000, rms=rms, votes=3,
                             valid=True, reboot=False, build='timing-v7', window=i+1)
                    self.incoming.put((name, 'reading', r))
        def send(self, command):
            assert self.name == 'reference'
            for output in service.send(command):self.incoming.put(('reference', 'result', output))
            if command == '@RESET\n':
                sent_resets[0] += 1
                if sent_resets[0] == 2:self.batch(12_000_000)
        def join(self, timeout=None):pass

    stop = threading.Event()
    commands = original_queue()
    sent_resets = [0]
    received_resets = [0]
    user_reset = [False]
    observed = []
    state = DashboardState()
    def event(kind, value):
        observed.append((kind, value))
        state.apply(kind, value, clock[0]/1e6)
        if kind=='result' and value.startswith('REF_RESET,'):received_resets[0] += 1
        if kind=='result' and 'DECISION=BASELINE_READY' in value and not user_reset[0]:
            user_reset[0] = True
            state.request_reset()
            commands.put('reset')
        if kind=='result' and 'DECISION=STUDENT_TALKING' in value and received_resets[0] >= 2:stop.set()

    build = ROOT/'firmware/build/reference_host'
    with tempfile.TemporaryDirectory(dir=build) as temp:
        folder = Path(temp)/'session'
        with patch('reference_nodes.SerialWorker', FakeWorker), \
             patch('reference_nodes.queue.Queue', TimedQueue), \
             patch('reference_nodes.time.monotonic_ns', lambda:clock[0]*1000):
            live('COM5', ['COM6'], folder, stop=stop, commands=commands, on_event=event, quiet=True)
        assert (folder/'pairs.jsonl').exists() and (folder/'decisions.jsonl').exists()
        assert any(k=='reading' for k, _ in observed)
        assert any(k=='result' and 'BASELINE_READY' in v for k, v in observed)
        assert any(k=='result' and 'DECISION=STUDENT_TALKING' in v for k, v in observed)
        assert observed[-1][0] == 'stopped' and not state.running
        assert state.ready and state.pairs == 20
        assert received_resets[0] == 2 and user_reset[0]


def session_check(folder):
    state = DashboardState()
    for i, raw in enumerate((folder/'decisions.jsonl').read_text().splitlines()):
        entry = json.loads(raw)
        state.apply('result', entry['line'], i*.5)
    print(f'Saved-session replay: {state.pairs} calibration pairs; baseline ready={state.ready}; '
          f"last reason={(state.result or {}).get('REASON')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path)
    args = parser.parse_args()
    state_checks()
    bridge_checks()
    if args.session:session_check(args.session)
    print('PASS: calibration display, paused speech, live/invalid/stale status, reset acknowledgement,')
    print('real C decisions through the bridge event stream, session logging and graceful stop.')
    print('No physical COM port was opened by these checks.')


if __name__ == '__main__':main()
