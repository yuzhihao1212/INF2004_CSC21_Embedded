"""Live two-Pico dashboard. Decisions still execute on the reference Pico.

Close other serial monitors first. Default roles: COM5 lecturer, COM6 student.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import math
import queue
import threading
import time

from reference_nodes import ROOT, live


REASONS = {
    'LECTURER_ONLY_CALIBRATION': 'Learning how much lecturer sound reaches the student mic. Keep student areas quiet.',
    'WAITING_FOR_LECTURER_SPEECH': 'Calibration paused: the reference mic needs at least 2/3 speech votes. Play/speak near the lecturer mic.',
    'CALIBRATION_NEEDS_LEVEL_VARIATION': 'More variation in lecturer level is needed to learn the baseline. Restart calibration if it remains stuck at 64 pairs.',
    'BASELINE_READY': 'Baseline learned. Keep the lecture playing, then speak near the student mic to test.',
    'WITHIN_LECTURER_BASELINE': 'Student level is within the learned lecturer range. A prior alert may hold for one window.',
    'EXCESS_WITHOUT_ENOUGH_SPEECH': 'Extra sound is present, but this window has too few speech votes. A prior alert may hold briefly.',
    'EXCESS_SPEECH': 'Extra level and speech votes passed the gates. This can also happen with lecturer speech plus noise.',
    'INVALID_OR_STALE_INPUT': 'A reading is invalid or too old. Check both node cards below.',
    'UNALIGNED_INPUTS': 'The two readings are too far apart in time. Waiting for an aligned pair.',
    'REPEATED_OR_OUT_OF_ORDER_INPUT': 'Repeated/out-of-order readings were rejected. Waiting for fresh pairs.',
}


def fields(line):
    return dict(part.split('=', 1) for part in line.split(',')[1:] if '=' in part)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):return None


class DashboardState:
    """UI-independent view state, also used to check replayed session output."""
    def __init__(self):
        self.readings = {}
        self.recent_faults = {}
        self.result = None
        self.result_seen = None
        self.pairs = 0
        self.ready = False
        self.awaiting_reset = False
        self.error = None
        self.running = False
        self.folder = ''
        self.student_history = deque(maxlen=240)
        self.reference_history = deque(maxlen=240)
        self.messages = deque(maxlen=80)

    def message(self, text, now):
        self.messages.append((now, text))

    def request_reset(self):
        self.awaiting_reset = True
        self.result = None
        self.ready = False
        self.pairs = 0
        self.student_history.clear()

    def apply(self, kind, value, now):
        if kind == 'session':
            self.running = True
            self.folder = value['folder']
            self.message('Connected bridge started. Waiting for both Picos.', now)
        elif kind == 'reading':
            reading = value['reading']
            self.readings[value['node']] = dict(reading=reading, seen=now)
            if not reading.get('valid'):
                previous = self.recent_faults.get(value['node'])
                self.recent_faults[value['node']] = dict(reading=reading, seen=now)
                if previous is None or now-previous['seen'] > 1.5:
                    _, detail = self.fault_message(value['node'], reading)
                    self.message(detail, now)
            if value['node'] == 'reference':self.reference_history.append((now, reading['rms']))
        elif kind == 'result':
            if value.startswith('REF_RESET,'):
                self.request_reset()
                self.awaiting_reset = False
                self.message('Calibration restarted. Lecturer only; keep the student area quiet.', now)
            elif value.startswith('REF_ERROR,'):
                self.error = value
                self.message(value, now)
            elif value.startswith('REF_RESULT,') and not self.awaiting_reset:
                result = fields(value)
                if result.get('NODE') != '1':return
                previous = self.result
                self.result, self.result_seen = result, now
                self.pairs = int(result.get('CAL_PAIRS', 0))
                if result.get('DECISION') == 'BASELINE_READY':self.ready = True
                if result.get('DECISION') == 'CALIBRATING':self.ready = False
                expected = number(result.get('EXPECTED_RMS')) if self.ready else None
                threshold = number(result.get('THRESHOLD_RMS')) if self.ready else None
                if result.get('DECISION') in ('UNKNOWN', 'BASELINE_READY'):expected = threshold = None
                self.student_history.append((now, number(result.get('STUDENT_RMS')), expected, threshold))
                if previous is None or (previous.get('DECISION'), previous.get('REASON')) != (result.get('DECISION'), result.get('REASON')):
                    self.message(REASONS.get(result.get('REASON'), result.get('REASON', 'Waiting')), now)
        elif kind == 'notice':self.message(value, now)
        elif kind == 'error':
            self.error = str(value)
            self.message(self.error, now)
        elif kind == 'stopped':
            self.running = False
            self.message('Stopped. COM ports released.', now)

    def node_status(self, name, now):
        item = self.readings.get(name)
        if not item:return 'WAITING', None
        age = max(0, now-item['seen'])
        if not self.running:return 'STOPPED', age
        if age > 1.5:return 'STALE', age
        return ('LIVE' if item['reading'].get('valid') else 'SIGNAL FAULT'), age

    @staticmethod
    def fault_message(name, reading):
        label = 'Student mic' if name == '1' else 'Lecturer mic'
        clipped = number(reading.get('clipped_samples'))
        if (clipped is not None and clipped >= 80) or reading.get('event') == 'CLIPPED':
            count = f'{int(clipped)}/8000 samples ({clipped/80:.1f}%) near ADC limits. ' if clipped is not None else ''
            return f'{label}: signal clipping', count+'This window is rejected; it is not a no-speech decision. Reduce the signal reaching the mic if it is close to a mouth or speaker. Clipping alone does not prove which sound caused it.'
        if reading.get('event') == 'TIMING_FAULT' or (number(reading.get('processing_us')) or 0) > 500000:
            return f'{label}: timing fault', 'This audio window missed timing requirements. The comparison waits for fresh valid windows.'
        return f'{label}: invalid signal', 'The node marked this window invalid. The comparison cannot classify it.'

    def banner(self, now):
        if self.error:return 'Connection / firmware error', self.error, '#fbdada'
        if not self.running:return 'Stopped — press Start', 'Lecturer: COM5, student: COM6 by default. Close other serial monitors first.', '#e8edf3'
        if self.awaiting_reset:return 'Restarting calibration', 'Waiting for the reference Pico to acknowledge reset.', '#fff0c2'
        statuses = [self.node_status(n, now)[0] for n in ('reference', '1')]
        if any(s in ('WAITING', 'STALE') for s in statuses):
            return 'Waiting for fresh readings from both Picos', 'Check the connection and node status below. Alerts are unavailable while readings are missing.', '#fff0c2'
        if 'SIGNAL FAULT' in statuses:
            for name in ('reference', '1'):
                if self.node_status(name, now)[0] == 'SIGNAL FAULT':
                    title, detail = self.fault_message(name, self.readings[name]['reading'])
                    return title, detail, '#fff0c2'
        if self.result is None or self.result_seen is None or now-self.result_seen > 2:
            return 'Waiting for paired comparison', 'Node readings are arriving; waiting for a current response from the reference Pico.', '#fff0c2'
        result = self.result
        decision = result.get('DECISION')
        reason = REASONS.get(result.get('REASON'), result.get('REASON', ''))
        if decision == 'UNKNOWN' and result.get('REASON') == 'INVALID_OR_STALE_INPUT':
            for name, item in self.recent_faults.items():
                if 0 <= self.result_seen-item['seen'] <= 1.5:
                    title, detail = self.fault_message(name, item['reading'])
                    return 'Cannot decide — recent '+title.lower(), detail+' Waiting for the next valid paired result.', '#fff0c2'
        if decision == 'CALIBRATING':return f'Calibrating: {self.pairs} / at least 20 pairs', reason, '#fff0c2'
        titles = {'BASELINE_READY': 'Baseline ready — you can test student speech',
                  'NO_STUDENT_TALKING': 'No additional sustained speech flagged',
                  'SPEECH_PENDING': 'Extra speech pending — not an alert yet',
                  'STUDENT_TALKING': 'Possible student talking',
                  'UNKNOWN': 'Cannot decide from this pair'}
        if result.get('HOLD') == '1':reason = 'Holding the previous alert through one weak window. '+reason
        return titles.get(decision, 'Waiting'), reason, '#fbdada' if decision == 'STUDENT_TALKING' else '#fff0c2' if decision in ('SPEECH_PENDING', 'UNKNOWN') else '#def0e2'


def launch(reference_port, student_port):
    import tkinter as tk
    from tkinter import ttk
    from serial.tools import list_ports

    root = tk.Tk()
    root.title('MOSAIC - live lecturer and student Picos')
    root.geometry('1080x900')
    root.minsize(900, 650)
    viewport = ttk.Frame(root)
    viewport.pack(fill='both', expand=True)
    scroller = tk.Canvas(viewport, highlightthickness=0)
    scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=scroller.yview)
    scrollbar.pack(side='right', fill='y')
    scroller.pack(side='left', fill='both', expand=True)
    scroller.configure(yscrollcommand=scrollbar.set)
    body = ttk.Frame(scroller, padding=18)
    body_id = scroller.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda _:scroller.configure(scrollregion=scroller.bbox('all')))
    scroller.bind('<Configure>', lambda e:scroller.itemconfigure(body_id, width=e.width))
    ttk.Label(body, text='Live classroom nodes', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
    ttk.Label(body, text='Actual Pico readings and decisions. Keep the lecturer sound source and microphones fixed during calibration.', wraplength=820).pack(anchor='w', pady=5)
    toolbar = ttk.Frame(body)
    toolbar.pack(fill='x', pady=8)
    ref_port, local_port = tk.StringVar(value=reference_port), tk.StringVar(value=student_port)
    ttk.Label(toolbar, text='Lecturer').pack(side='left')
    ref_selector = ttk.Combobox(toolbar, textvariable=ref_port, width=10)
    ref_selector.pack(side='left', padx=(5, 14))
    ttk.Label(toolbar, text='Student').pack(side='left')
    student_selector = ttk.Combobox(toolbar, textvariable=local_port, width=10)
    student_selector.pack(side='left', padx=(5, 12))

    def refresh_ports():
        ports = [p.device for p in list_ports.comports()]
        ref_selector.configure(values=ports)
        student_selector.configure(values=ports)

    ttk.Button(toolbar, text='Refresh ports', command=refresh_ports).pack(side='left', padx=4)
    event_queue, commands = queue.Queue(), queue.Queue()
    state = DashboardState()
    worker = None
    stop = threading.Event()
    closing = False

    def emit(kind, value):event_queue.put((time.monotonic(), kind, value))

    def start():
        nonlocal state, worker, stop, commands
        if worker is not None and worker.is_alive():return
        r, s = ref_port.get().strip().upper(), local_port.get().strip().upper()
        state = DashboardState()
        if not r or not s or r == s:
            state.error = 'Choose two different COM ports.';return
        while not event_queue.empty():event_queue.get_nowait()
        stop, commands = threading.Event(), queue.Queue()
        state.running = True
        folder = ROOT/'ml/diagnostics/reference_sessions'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')

        def run():
            stopped = False
            def notify(kind, value):
                nonlocal stopped
                if kind == 'stopped':stopped = True
                emit(kind, value)
            try:live(r, [s], folder, stop=stop, commands=commands, on_event=notify, quiet=True)
            except Exception as error:
                emit('error', str(error))
            finally:
                if not stopped:emit('stopped', None)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()

    def stop_session():stop.set()

    def reset():
        if state.running:
            state.request_reset()
            commands.put('reset')

    start_button = ttk.Button(toolbar, text='Start', command=start)
    start_button.pack(side='left', padx=4)
    stop_button = ttk.Button(toolbar, text='Stop / release ports', command=stop_session)
    stop_button.pack(side='left', padx=4)
    reset_button = ttk.Button(toolbar, text='Recalibrate', command=reset)
    reset_button.pack(side='left', padx=4)
    title, explanation = tk.StringVar(), tk.StringVar()
    banner = tk.Label(body, textvariable=title, font=('Segoe UI', 19, 'bold'), anchor='w', padx=12, pady=12)
    banner.pack(fill='x', pady=(6, 4))
    ttk.Label(body, textvariable=explanation, wraplength=820).pack(anchor='w', pady=4)
    calibration = tk.StringVar(value='Calibration: 0 / at least 20 usable lecturer-speech pairs')
    ttk.Label(body, textvariable=calibration).pack(anchor='w', pady=(8, 2))
    progress = ttk.Progressbar(body, maximum=20)
    progress.pack(fill='x', pady=(0, 10))
    cards = ttk.Frame(body)
    cards.pack(fill='x')
    card_vars = {}
    for name, label in [('reference', 'Lecturer / reference mic'), ('1', 'Student mic')]:
        card = ttk.LabelFrame(cards, text=label, padding=12)
        card.pack(side='left', fill='both', expand=True, padx=(0, 8))
        variables = [tk.StringVar() for _ in range(5)]
        for i, var in enumerate(variables):
            ttk.Label(card, textvariable=var, font=('Segoe UI', 14, 'bold') if i==0 else ('Segoe UI', 10)).pack(anchor='w', pady=2)
        card_vars[name] = variables
    metrics = tk.StringVar()
    ttk.Label(body, textvariable=metrics, font=('Consolas', 12)).pack(anchor='w', pady=12)
    ttk.Label(body, text='Student level: blue    Expected lecturer at student: grey    Alert threshold: orange    (ADC RMS, not dB)', wraplength=820).pack(anchor='w')
    student_plot = tk.Canvas(body, height=175, background='#f5f7fa', highlightthickness=0)
    student_plot.pack(fill='x', pady=5)
    ttk.Label(body, text='Lecturer/reference mic level (ADC RMS)').pack(anchor='w')
    reference_plot = tk.Canvas(body, height=95, background='#f5f7fa', highlightthickness=0)
    reference_plot.pack(fill='x', pady=5)
    ttk.Label(body, text='Local speech at the student mic can be the lecturer. The main banner is the reference comparison.', wraplength=820).pack(anchor='w', pady=3)
    ttk.Label(body, text='Possible talking is an alert candidate: lecturer speech mixed with noise can still cause false positives.', foreground='#8b4513', wraplength=820).pack(anchor='w')
    ttk.Label(body, text='Recent status changes').pack(anchor='w', pady=(10, 2))
    messages = tk.Text(body, height=5, wrap='word', state='disabled', font=('Segoe UI', 10))
    messages.pack(fill='x')
    log_path = tk.StringVar(value='Logs will be saved when you press Start.')
    ttk.Entry(body, textvariable=log_path, state='readonly').pack(fill='x', pady=6)

    def plot(canvas, rows, colors, now):
        canvas.delete('all')
        rows = [r for r in rows if now-r[0] <= 60]
        if not rows:return
        values = [v for r in rows for v in r[1:] if v is not None and math.isfinite(v)]
        ceiling = max([10]+values)*1.15
        width, height = max(canvas.winfo_width(), 200), int(canvas['height'])
        left, right, top, bottom = 55, width-12, 12, height-23
        for i in range(4):
            level = ceiling*i/3
            y = bottom-(bottom-top)*i/3
            canvas.create_line(left, y, right, y, fill='#dce1e8')
            canvas.create_text(left-6, y, text=f'{level:.0f}', anchor='e', fill='#5f6670')
        start_time = max(rows[0][0], now-60)
        duration = max(10, now-start_time)
        canvas.create_text(left, height-6, text='Recent readings', anchor='w', fill='#5f6670')
        for column, color in enumerate(colors, 1):
            points = []
            def draw():
                if len(points) >= 4:canvas.create_line(*points, fill=color, width=2)
                elif len(points) == 2:
                    x, y = points
                    canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, outline=color)
            for row in rows:
                value = row[column]
                if value is None:
                    draw();points=[];continue
                points.extend((left+(row[0]-start_time)/duration*(right-left), bottom-value/ceiling*(bottom-top)))
            draw()

    last_messages = None
    def render():
        nonlocal last_messages
        while True:
            try:seen, kind, value = event_queue.get_nowait()
            except queue.Empty:break
            state.apply(kind, value, seen)
        now = time.monotonic()
        text, detail, color = state.banner(now)
        title.set(text);explanation.set(detail);banner.configure(background=color)
        active = worker is not None and worker.is_alive()
        start_button.configure(state='disabled' if active else 'normal')
        stop_button.configure(state='normal' if active else 'disabled')
        reset_button.configure(state='normal' if active else 'disabled')
        ref_selector.configure(state='disabled' if active else 'normal')
        student_selector.configure(state='disabled' if active else 'normal')
        progress['value'] = min(state.pairs, 20)
        calibration.set(f"Calibration: {state.pairs} / at least 20 usable lecturer-speech pairs" + (' — READY' if state.ready else ' — lecturer only, please wait'))
        for name, variables in card_vars.items():
            status, age = state.node_status(name, now)
            item = state.readings.get(name)
            variables[0].set(f"{ref_port.get() if name=='reference' else local_port.get()} — {status}" + (f' ({age:.1f}s ago)' if age is not None else ''))
            if item:
                r = item['reading']
                variables[1].set(f"Sound level: {r['rms']:.1f} ADC RMS")
                p = number(r.get('pulse_prob'))
                variables[2].set(f"Speech votes: {r['votes']}/3" + (f' | PulseVAD p={p:.3f}' if p is not None else ''))
                variables[3].set(f"Local speech: {r.get('event') or 'not logged'} | near-rail samples: {r.get('clipped_samples', '—')}")
                processing = number(r.get('processing_us'))
                variables[4].set(f"{r.get('build', '')} | window {r.get('window', '—')}" + (f' | work {processing/1000:.0f} ms' if processing is not None else ''))
            else:
                for var in variables[1:]:var.set('Waiting for telemetry…')
        result = state.result or {}
        expected = number(result.get('EXPECTED_RMS')) if state.ready and result.get('DECISION') not in ('UNKNOWN', 'BASELINE_READY') else None
        threshold = number(result.get('THRESHOLD_RMS')) if expected is not None else None
        def fmt(value):return '—' if value is None else f'{value:.1f}'
        metrics.set(f"Expected lecturer at student: {fmt(expected)}    Alert threshold: {fmt(threshold)}    HOLD: {result.get('HOLD', '0')}")
        plot(student_plot, state.student_history, ('#2463b4', '#7a8494', '#d47c12'), now)
        plot(reference_plot, state.reference_history, ('#398c62',), now)
        if state.folder:log_path.set(state.folder)
        current_messages = tuple(state.messages)
        if current_messages != last_messages:
            messages.configure(state='normal');messages.delete('1.0', 'end')
            for _, message in state.messages:messages.insert('end', message+'\n')
            messages.see('end');messages.configure(state='disabled');last_messages=current_messages
        if closing:
            if not active:root.destroy();return
        root.after(150, render)

    def close():
        nonlocal closing
        closing = True
        stop.set()
        title.set('Stopping and releasing COM ports…')

    root.protocol('WM_DELETE_WINDOW', close)
    refresh_ports()
    render()
    try:root.mainloop()
    finally:stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-port', default='COM5')
    parser.add_argument('--student-port', default='COM6')
    args = parser.parse_args()
    launch(args.reference_port, args.student_port)


if __name__ == '__main__':main()
