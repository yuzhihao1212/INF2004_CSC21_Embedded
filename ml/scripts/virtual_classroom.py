"""Interactive classroom with the Pico C speech model and comparison service.

Default mode classifies mixed audio. --synthetic retains the level-only demo.
--verify checks synthetic logic; --verify-audio checks the audio model pipeline.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import math

from reference_nodes import NativeService, ROOT, pair_command


class VirtualClassroom:
    """One virtual reference and one virtual student, in 500 ms windows."""

    def __init__(self):
        self.service = NativeService()
        self.time_us = 0
        self.restart()

    def restart(self):
        self.service.send('@RESET\n')
        self.calibration_pairs = 0
        self.ready = False

    def step(self, lecturer=150, lecturer_speech=True, student=0,
             student_speech=False, noise=0, reference_valid=True, burst=False,
             noise_burst=False):
        self.time_us += 500000
        calibrating = not self.ready
        if calibrating:
            # Deliberately varied lecturer-only evidence for baseline fitting.
            lecturer = 100 + (self.calibration_pairs % 7) * 35
            lecturer_speech = True
            student, student_speech, noise, reference_valid = 0, False, 0, True
            self.calibration_pairs += 1
        reference_rms = math.sqrt(10**2 + (lecturer if lecturer_speech else 0)**2)
        if burst and not calibrating:
            student, student_speech = 200, True
        if noise_burst and not calibrating:
            noise = 200
        # Synthetic power mixture, NOT an acoustic propagation/audio model.
        student_rms = math.sqrt(.04 * reference_rms**2 + 100 + student**2 + noise**2)
        votes = 3 if lecturer_speech or student_speech else 0
        ref = dict(time_us=self.time_us, rms=reference_rms,
                   votes=3 if lecturer_speech else 0, valid=reference_valid)
        local = dict(time_us=self.time_us, rms=student_rms, votes=votes, valid=True)
        # When testing a noise-only case, turn lecturer speech off: an active
        # lecturer can supply valid speech votes underneath a loud noise.
        line, = self.service.send(pair_command(1, self.time_us, ref, local))
        result = dict(part.split('=', 1) for part in line.split(',')[1:])
        if result['DECISION'] == 'BASELINE_READY':
            self.ready = True
        return dict(time_us=self.time_us, reference=ref, student=local,
                    calibrating=calibrating, noise_burst=bool(noise_burst and not calibrating), result=result)


PRESETS = {
    'Lecturer only': dict(lecturer=150, lecturer_speech=True),
    'Louder lecturer': dict(lecturer=450, lecturer_speech=True),
    'Student joins': dict(lecturer=150, lecturer_speech=True, student=140, student_speech=True),
    'Noise only': dict(lecturer_speech=False, noise=200),
    'Noise over lecturer': dict(lecturer=150, lecturer_speech=True, noise=200),
    'Brief selected noise': dict(lecturer=150, lecturer_speech=True),
    'Reference lost': dict(lecturer=150, lecturer_speech=True, student=140,
                           student_speech=True, reference_valid=False),
    'Silence': dict(lecturer_speech=False),
}


def verify():
    classroom = VirtualClassroom()
    records = [classroom.step() for _ in range(20)]
    assert classroom.ready and records[-1]['result']['DECISION'] == 'BASELINE_READY'

    def run(name, count=3):
        frames = [classroom.step(**PRESETS[name]) for _ in range(count)]
        records.extend(frames)
        return frames[-1]['result']['DECISION']

    assert run('Lecturer only') == 'NO_STUDENT_TALKING'
    # Even with lecturer speech providing votes, separated one-window noise
    # spikes cannot START an alert. This is duration gating, not cough ML.
    for _ in range(3):
        records.append(classroom.step(noise_burst=True))
        assert records[-1]['student']['rms'] > float(records[-1]['result']['THRESHOLD_RMS'])
        assert records[-1]['student']['votes'] == 3
        assert records[-1]['result']['DECISION'] == 'SPEECH_PENDING'
        assert run('Lecturer only', 1) == 'NO_STUDENT_TALKING'
    assert run('Louder lecturer') == 'NO_STUDENT_TALKING'
    records.append(classroom.step(burst=True))
    assert records[-1]['result']['DECISION'] == 'SPEECH_PENDING'
    assert run('Lecturer only') == 'NO_STUDENT_TALKING'
    assert run('Student joins', 2) == 'STUDENT_TALKING'
    assert run('Reference lost', 1) == 'UNKNOWN'
    assert run('Noise only') == 'NO_STUDENT_TALKING'
    # An important limitation: lecturer speech + unrelated loud noise can pass.
    assert run('Noise over lecturer', 2) == 'STUDENT_TALKING'
    assert run('Silence') == 'NO_STUDENT_TALKING'
    classroom.restart()
    assert not classroom.ready
    records.append(classroom.step())
    assert records[-1]['result']['DECISION'] == 'CALIBRATING'
    folder = ROOT / 'ml/diagnostics/virtual_classroom'
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / 'verification.json'
    report.write_text(json.dumps(dict(passed=True, synthetic=True, records=records,
        limitation='Speech votes are simulated. Noise over lecturer speech can trigger.'), indent=2)+'\n')
    print('PASS: virtual calibration, lecturer-only, louder lecturer, brief burst, three separated noise spikes, student joins,')
    print('reference loss, noise-only, noise-over-speech limitation, silence and reset.')
    print('Synthetic comparison test only; no neural/audio accuracy measurement.')
    print('Report:', report)


def launch(synthetic=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    if synthetic:
        classroom = VirtualClassroom()
    else:
        from virtual_classroom_audio import AudioClassroom
        classroom = AudioClassroom()
    root = tk.Tk()
    root.title('MOSAIC virtual classroom - ' + ('synthetic votes' if synthetic else 'actual C speech model on audio'))
    root.geometry('1050x900' if not synthetic else '980x830')
    root.minsize(900, 740)
    viewport = ttk.Frame(root)
    viewport.pack(fill='both', expand=True)
    viewport_canvas = tk.Canvas(viewport, highlightthickness=0)
    scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=viewport_canvas.yview)
    scrollbar.pack(side='right', fill='y')
    viewport_canvas.pack(side='left', fill='both', expand=True)
    viewport_canvas.configure(yscrollcommand=scrollbar.set)
    body = ttk.Frame(viewport_canvas, padding=18)
    body_window = viewport_canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda _:viewport_canvas.configure(scrollregion=viewport_canvas.bbox('all')))
    viewport_canvas.bind('<Configure>', lambda event:viewport_canvas.itemconfigure(body_window, width=event.width))
    ttk.Label(body, text='Virtual lecturer + student nodes', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(body, text=('LOGIC ONLY: synthetic levels and speech votes; no audio classification.' if synthetic else
              'AUDIO MODE: both virtual microphones run the deployed speech model on mixed waveforms. No assigned speech votes.'),
              wraplength=910).pack(anchor='w', pady=(4, 12))
    state_text = tk.StringVar(value='Calibrating lecturer-only baseline…')
    state_label = tk.Label(body, textvariable=state_text, anchor='w', font=('Segoe UI', 20, 'bold'),
                          background='#e8edf3', padx=12, pady=12)
    state_label.pack(fill='x')
    reason_text = tk.StringVar()
    ttk.Label(body, textvariable=reason_text).pack(anchor='w', pady=8)

    controls = ttk.Frame(body)
    controls.pack(fill='x')
    variables = {}
    reference_box = ttk.LabelFrame(controls, text='Reference node — lecturer', padding=12)
    student_box = ttk.LabelFrame(controls, text='Student node', padding=12)
    reference_box.pack(side='left', fill='both', expand=True, padx=(0, 6))
    student_box.pack(side='left', fill='both', expand=True, padx=(6, 0))

    def slider(parent, key, text, default, maximum):
        variables[key] = tk.DoubleVar(value=default)
        ttk.Label(parent, text=text).pack(anchor='w')
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 8))
        ttk.Scale(row, from_=0, to=maximum, variable=variables[key]).pack(side='left', fill='x', expand=True)
        label = ttk.Label(row, width=5)
        label.pack(side='right')
        def update(*_):label.configure(text=f'{variables[key].get():.0f}')
        variables[key].trace_add('write', update)
        update()

    def checkbox(parent, key, text, default):
        variables[key] = tk.BooleanVar(value=default)
        ttk.Checkbutton(parent, text=text, variable=variables[key]).pack(anchor='w', pady=3)

    slider(reference_box, 'lecturer', 'Lecturer level (synthetic ADC RMS)' if synthetic else 'Lecturer clip gain (nominal ADC RMS)', 150, 500)
    checkbox(reference_box, 'lecturer_speech', 'Lecturer speaking — simulated evidence' if synthetic else 'Include lecturer speech audio', True)
    checkbox(reference_box, 'reference_valid', 'Reference connected and valid', True)
    slider(student_box, 'student', 'Additional sound near student' if synthetic else 'Student speech clip gain', 0, 300)
    slider(student_box, 'noise', 'Additional non-speech noise' if synthetic else 'Selected noise clip gain', 0, 300)
    checkbox(student_box, 'student_speech', 'Additional sound is speech — simulated evidence' if synthetic else 'Include student speech audio', False)

    source_text = tk.StringVar()
    if not synthetic:
        source_row = ttk.Frame(body)
        source_row.pack(fill='x', pady=6)
        ttk.Label(source_row, text='Noise audio:').pack(side='left')
        noise_choice = tk.StringVar(value=classroom.noise_name)
        noise_selector = ttk.Combobox(source_row, textvariable=noise_choice, values=list(classroom.noises), state='readonly', width=14)
        noise_selector.pack(side='left', padx=6)
        noise_selector.bind('<<ComboboxSelected>>', lambda _:setattr(classroom, 'noise_name', noise_choice.get()))

        def update_sources():
            source_text.set(f'Reference: {classroom.lecturer.label} | Student: {classroom.student.label}')

        def load_audio(role):
            path = filedialog.askopenfilename(title=f'Choose {role} WAV', filetypes=[('Audio files', '*.wav *.flac *.ogg'), ('All files', '*.*')])
            if not path:return
            try:classroom.load(role, path)
            except (OSError, ValueError, RuntimeError) as error:
                messagebox.showerror('Cannot load audio', str(error));return
            history.clear()
            noise_selector.configure(values=list(classroom.noises))
            noise_choice.set(classroom.noise_name)
            update_sources()

        for role in ('lecturer', 'student', 'noise'):
            ttk.Button(source_row, text=f'Load {role} WAV', command=lambda role=role:load_audio(role)).pack(side='left', padx=3)
        update_sources()
        ttk.Label(body, textvariable=source_text, wraplength=980).pack(anchor='w')

    action_row = ttk.Frame(body)
    action_row.pack(fill='x', pady=(12, 4))
    ttk.Label(action_row, text='Scenario:').pack(side='left')
    selected = tk.StringVar(value='Lecturer only')
    selector = ttk.Combobox(action_row, textvariable=selected, values=list(PRESETS), state='readonly', width=24)
    selector.pack(side='left', padx=8)
    burst_remaining = 0
    duration_text = tk.StringVar(value='A new alert needs 2 consecutive qualifying 500 ms windows; one spike is only pending.')

    def preset():
        nonlocal burst_remaining
        burst_remaining = 1 if selected.get() == 'Brief selected noise' else 0
        duration_text.set('Brief noise queued for ONE window, then lecturer only. Try from NO STUDENT TALKING.'
                          if burst_remaining else 'A new alert needs 2 consecutive qualifying 500 ms windows; one spike is only pending.')
        defaults = dict(lecturer=150, lecturer_speech=False, student=0,
                        student_speech=False, noise=0, reference_valid=True)
        defaults.update(PRESETS[selected.get()])
        for key, value in defaults.items():variables[key].set(value)

    def burst():
        nonlocal burst_remaining
        selected.set('Brief selected noise')
        preset()

    def restart():
        nonlocal burst_remaining
        burst_remaining = 0
        classroom.restart()
        history.clear()
        selected.set('Lecturer only')
        preset()

    ttk.Button(action_row, text='Apply', command=preset).pack(side='left')
    ttk.Button(action_row, text='Brief selected noise', command=burst).pack(side='left', padx=8)
    ttk.Button(action_row, text='Recalibrate', command=restart).pack(side='left')
    ttk.Label(body, text=('Calibration takes 10 seconds; controls take effect once BASELINE_READY appears.' if synthetic else
              'Automatic lecturer-only calibration: wait for 20 speech-positive pairs and BASELINE READY. Controls apply afterward.'),
              wraplength=910).pack(anchor='w', pady=4)
    ttk.Label(body, textvariable=duration_text, wraplength=910).pack(anchor='w', pady=4)
    numbers = tk.StringVar()
    ttk.Label(body, textvariable=numbers, font=('Consolas', 11)).pack(anchor='w', pady=8)
    model_text = tk.StringVar()
    if not synthetic:ttk.Label(body, textvariable=model_text, wraplength=980).pack(anchor='w', pady=3)
    ttk.Label(body, text='Student sound: blue     Expected lecturer baseline: grey     Alert threshold: orange',
              wraplength=910).pack(anchor='w')
    canvas = tk.Canvas(body, height=160, background='#f5f7fa', highlightthickness=0)
    canvas.pack(fill='both', expand=True, pady=6)
    ttk.Label(body, text='Limitation: the model can accept or reject the mixture; speech plus loud noise may still cause a false alert.',
              wraplength=910, foreground='#8b4513').pack(anchor='w', pady=3)
    ttk.Label(body, text=('A brief simulated burst is not a recorded cough test. This mode does not classify audio.' if synthetic else
              'Default speech clips are spoken digits, not classroom lectures. Cough/noise clips are real recordings; mixing and microphone gain are simulated.'),
              wraplength=910).pack(anchor='w')
    folder = ROOT / 'ml/diagnostics/virtual_classroom' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    folder.mkdir(parents=True, exist_ok=False)
    log = (folder / 'events.jsonl').open('x', encoding='utf-8')
    if not synthetic:
        audio_row = ttk.Frame(body)
        audio_row.pack(fill='x', pady=4)
        audio_path = tk.StringVar()
        last_saved = None

        def save_audio(play=False):
            nonlocal last_saved
            if play and last_saved is not None:
                saved = last_saved
            else:
                saved = classroom.save_audio(folder / ('audio_'+datetime.now(timezone.utc).strftime('%H%M%S_%f')))
                last_saved = saved
                audio_path.set(f'Saved reference.wav + student.wav: {saved.parent}')
                print('Saved audio:', saved.parent, flush=True)
            if play:
                import os
                if os.name == 'nt':
                    import winsound
                    winsound.PlaySound(str(saved), winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:messagebox.showinfo('Saved audio', str(saved))

        ttk.Button(audio_row, text='Save recent audio (up to 20s)', command=save_audio).pack(side='left')
        ttk.Button(audio_row, text='Play saved student WAV', command=lambda:save_audio(True)).pack(side='left', padx=6)
        ttk.Label(body, textvariable=audio_path, wraplength=980).pack(anchor='w')
    ttk.Label(body, text=f'Event log: {folder.relative_to(ROOT)}', wraplength=910).pack(anchor='w', pady=4)
    history = deque(maxlen=80)
    after_id = None

    def tick():
        nonlocal burst_remaining, after_id
        inputs = {key: var.get() for key, var in variables.items()}
        burst_this_window = bool(burst_remaining) and classroom.ready
        record = classroom.step(**inputs, noise_burst=burst_this_window)
        if burst_this_window:
            burst_remaining -= 1
            duration_text.set('One 500 ms noise excerpt applied; it cannot START an alert alone. Model scores below show whether it detected speech.')
        result = record['result']
        decision = result['DECISION']
        state_text.set(decision.replace('_', ' '))
        color = '#fbdada' if decision == 'STUDENT_TALKING' else '#fff0c2' if decision in ('UNKNOWN', 'SPEECH_PENDING') else '#def0e2'
        state_label.configure(background=color)
        onset = 'Onset: 1/2 qualifying windows (no new alert yet)' if decision == 'SPEECH_PENDING' else (
            'Alert held through one weak window' if result['HOLD'] == '1' else
            'Alert: at least 2 qualifying windows' if decision == 'STUDENT_TALKING' else '')
        reason_text.set(f"{result['REASON']}   |   Calibration {result['CAL_PAIRS']}/20   |   HOLD={result['HOLD']}" +
                        (f'\n{onset}' if onset else ''))
        numbers.set(f"Reference {record['reference']['rms']:6.1f}    Student {record['student']['rms']:6.1f}    "
                    f"Expected {float(result['EXPECTED_RMS']):6.1f}    Threshold {float(result['THRESHOLD_RMS']):6.1f}    "
                    f"Votes {record['student']['votes']}/3")
        if not synthetic:
            r, s = record['reference'], record['student']
            probability = 'own_prob' if classroom.model.own_head else 'pulse_prob'
            model_text.set(f"{s['model']} | Reference speech probability {r[probability]:.3f} ({r['votes']}/3 votes) | "
                           f"Student mixture {s[probability]:.3f} ({s['votes']}/3 votes) | Old local detector: {s['event']}")
        record['controls'] = inputs
        record['burst'] = burst_this_window
        log.write(json.dumps(record)+'\n')
        log.flush()
        history.append((record['student']['rms'], float(result['EXPECTED_RMS']), float(result['THRESHOLD_RMS'])))
        canvas.delete('all')
        width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 100)
        ceiling = max(100, max(max(point) for point in history) * 1.15)
        canvas.create_text(8, 8, anchor='nw', text=f'{ceiling:.0f} RMS', fill='#5f6670')
        for column, color in enumerate(('#2463b4', '#7a8494', '#d47c12')):
            points = []
            for i, point in enumerate(history):
                points.extend((i * (width-20)/79 + 10, height-12-point[column]*(height-35)/ceiling))
            if len(points) >= 4:canvas.create_line(*points, fill=color, width=2)
        after_id = root.after(500, tick)

    def close():
        if after_id is not None:root.after_cancel(after_id)
        log.close()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    tick()
    try:root.mainloop()
    finally:
        if not log.closed:log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument('--verify', action='store_true', help='Run synthetic checks without opening a window')
    options.add_argument('--verify-audio', action='store_true', help='Run the actual model on audio scenarios and save reports/WAVs')
    options.add_argument('--synthetic', action='store_true', help='Open the old logic-only mode with assigned speech votes')
    args = parser.parse_args()
    if args.verify:verify()
    elif args.verify_audio:
        from virtual_classroom_audio import verify_audio
        verify_audio()
    else:launch(synthetic=args.synthetic)


if __name__ == '__main__':main()
