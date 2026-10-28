# Lecturer reference and student-node comparison

`audio_talking` now includes a lecturer-reference comparison service. The neural
model still detects speech on each Pico. The reference Pico makes the final
`STUDENT_TALKING` decision using paired readings from itself and student nodes.
For this prototype, a PC connects the Picos over USB and forwards the readings.
Wi-Fi transport and fusion messaging are not integrated yet.

## Run without microphones

For an interactive virtual classroom, from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/virtual_classroom.py
```

No Picos, microphones or COM ports are needed. **The default now runs the actual
Pico C speech model on audio**, not assigned speech flags. Host GCC builds the
deployed frontend, neural network, local speech policy, ADC quality code and
reference comparison. Tkinter, NumPy, SciPy and SoundFile are already installed
in this workspace's `.venv`.

The two virtual microphone waveforms mix:

- Reference: lecturer speech plus a small generated noise floor.
- Student: attenuated lecturer speech, optional student speech, optional selected
  recorded noise and an independent small noise floor.

Both waveforms are converted to unsigned 12-bit ADC samples. Each runs the same
three overlapping 200 ms model contexts per 500 ms block as the Pico. Speech
votes come from the active C model's 0.5 probability threshold. The default is
pretrained PulseVAD; the locally trained head is also evaluated, and the active
model follows `talking_uses_own_head()` in the firmware. Audio-source checkboxes
include/mute audio; they **do not assign the model's predictions**.

Wait for 20 speech-positive lecturer pairs and `BASELINE_READY` (about ten
seconds with these default clips; potentially longer with custom audio). Then
choose a scenario and click **Apply**: Lecturer only, Louder lecturer, Student
joins, Noise only, Noise over lecturer, Brief selected noise, Reference lost or
Silence. Choose **Cough 1**, **Cough 2**, **Rain** or **Wood knock** in the noise
selector. The noise-gain slider applies the selected noise continuously.
**Brief selected noise** applies the selected recording's highest-energy 500 ms
excerpt once, then returns to lecturer-only controls. A brief excerpt can
produce no speech evidence or pending speech; one window alone cannot start
an alert. Repeated coughs spanning several windows can still trigger.

The screen shows reference and mixture probabilities/votes, the **old local
detector's output**, the comparison result, level traces, threshold and hold
state. **Load lecturer/student/noise WAV** replaces the corresponding default
source and starts calibration again. No microphone recording is required.
**Recalibrate** resets the baseline. Close the window to stop.

**Save recent audio** writes `reference.wav`, `student.wav` and `windows.json`
for up to the last 20 seconds. **Play saved student WAV** plays the last saved
mixture on Windows (or saves a snapshot first if none exists). These WAVs
preserve the exact ADC samples classified by the model; no playback-only gain
or denoising is applied. Event logs and snapshots are saved under
`ml/diagnostics/virtual_classroom/<timestamp>/`.

Defaults use FSDD spoken digits from different speakers as speech proxies,
plus public ESC-50 noises. These are **not actual lectures/conversations** and
the mixture is not a room acoustics simulation. Per-file scaling preserves
within-clip dynamics; there is no per-window normalisation. The host test does
not measure physical microphone noise, distance, echo, or Pico timing. ESC-50
audio is CC BY-NC and FSDD is CC BY-SA 4.0; attribution/provenance is retained
with the audio sources and exported snapshots.

Audio is already prepared locally. On another checkout, prepare the existing
public subset and two additional cough recordings:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/fetch_vad_audio.py
& '.\.venv\Scripts\python.exe' ml/scripts/prepare_virtual_audio.py
```

Run the actual-model scenarios without opening a window:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/virtual_classroom.py --verify-audio
```

This saves a per-scenario report and reference/student WAVs under
`ml/diagnostics/virtual_classroom/audio_test_<timestamp>/`. It checks actual
model-derived votes, quality faults, calibration, baseline comparison and
lossless WAV replay. Cases include lecturer-only, added speech, two real cough
recordings, isolated and consecutive cough excerpts, rain, knocks, reference
loss and silence. Each case runs 20 test windows after its own calibration.
False alerts are reported, not suppressed or asserted away. These counts are
demonstration outputs, **not classroom accuracy estimates**.

The old logic-only environment is still available explicitly:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/virtual_classroom.py --synthetic
& '.\.venv\Scripts\python.exe' ml/scripts/virtual_classroom.py --verify
```

Only that mode assigns synthetic speech votes. Its brief-noise test verifies
duration gating, not the model's ability to classify recorded noises.

For the existing scripted terminal demonstration instead:

From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/reference_nodes.py --simulate
```

This runs the **actual firmware C decision service** on the PC using synthetic
inputs. Host GCC is required for simulation, but not for the live USB bridge.
The output demonstrates calibration, louder lecturer speech, isolated brief
speech-like bursts, loud non-speech, sustained extra speech and invalid inputs.
It is a logic demonstration, not a recording test or an accuracy measurement.

## Run with two Picos

The live dashboard shows physical-node readings, calibration progress and the
reference Pico's actual decisions. It does not use the virtual audio mixer.
Stop the console bridge with **Ctrl+C** first so it releases both COM ports,
then run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/reference_dashboard.py --reference-port COM5 --student-port COM6
```

Click **Start** in the window. COM5 is the lecturer/reference and COM6 is the
student in this setup. The port selectors can be changed before starting.
The dashboard shows:

- Both nodes' connection age, ADC RMS levels, speech votes, model probability,
  local speech output, firmware version, work time and near-rail samples.
  Near-rail counts of 80 or more out of 8000 invalidate a block. The banner
  names the affected microphone and reports clipping explicitly, including
  when an invalid-pair response follows a recently clipped block. Timing faults
  are shown separately. A clipped window is not a negative speech prediction;
  it is unusable input. Clipping alone does not identify the noise source.
- Calibration count out of at least 20 usable lecturer-speech pairs. It explains
  when calibration pauses because the reference has too few speech votes.
- The student's learned expected lecturer level and threshold, once ready.
  They display as unavailable during calibration rather than misleading zeros.
- A main comparison banner: calibrating, ready, pending, possible talking or
  unable to decide. Local speech at the student mic can simply be the lecturer;
  it is not itself an additional-student alert.
- Scrolling student/reference level plots and recent human-readable status
  changes. Missing/invalid/stale data disables an old alert on the display.

Keep student areas quiet while the lecturer speaks until **Baseline ready**.
The progress counts usable speech windows, not elapsed seconds. **Recalibrate**
resets the learned baseline and waits for the Pico acknowledgement before using
new results. **Stop / release ports** or closing the window stops the bridge
and releases the ports. Logs use the same `ml/diagnostics/reference_sessions/`
folder and files as the console bridge; the live dashboard does not record WAVs.
The final comparison still executes on the reference Pico.

Offline checks exercise the actual C service through simulated serial readers,
including mid-session recalibration and closing the bridge:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/verify_reference_dashboard.py
```

The firmware is already built at `firmware/build/audio/audio_talking.uf2`.
Flash it onto both the lecturer and student Pico using BOOTSEL. This build
reports `BUILD=timing-v7`. Microphone wiring stays AUD -> GP26 / ADC0,
VCC -> 3V3, GND -> GND.

Close miniterm, Serial Monitor and other capture scripts. List the ports:

```powershell
& '.\.venv\Scripts\python.exe' -m serial.tools.list_ports
```

If the lecturer Pico is COM5 and student Pico is COM6, run:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/reference_nodes.py --reference-port COM5 --student-port COM6
```

Replace those port names with the actual ports. Add another `--student-port`
option for each additional student Pico, up to seven. Both ports must be
connected to the PC running the bridge.

1. Keep the microphones in their demonstration positions. Let only the
   lecturer speak, with natural pauses and changes in voice level. Keep the
   student areas quiet during calibration.
2. Wait for `DECISION=BASELINE_READY` for each student node. Each needs at
   least 20 valid lecturer-speech pairs: about ten seconds of usable voiced
   windows, potentially longer with pauses or timing faults. Constant reference
   levels produce `CALIBRATION_NEEDS_LEVEL_VARIATION`; restart if it remains
   there after 64 pairs.
3. Continue lecturer speech, then have someone talk near a student node.
   Sustained extra speech should produce `DECISION=STUDENT_TALKING`.
   `SPEECH_PENDING` means one qualifying window, not yet a confirmed event.
4. Press **Ctrl+C** to stop. Restart to recalibrate after moving nodes or
   changing microphone gains or amplification.

The bridge prints decisions and saves paired evidence and decisions under
`ml/diagnostics/reference_sessions/<timestamp>/`. This mode saves JSONL logs,
not WAV audio. The separate `monitor_speech.py` workflow still saves WAV audio
from one node; do not run both against the same COM port.

## Decision logic

Each student gets a frozen lecturer-only baseline, fitted in signal power:

```text
expected_student_RMS = sqrt(gain * reference_RMS² + background_power)
threshold = sqrt(expected_power + upper_calibration_residual) * 1.25 + 4
```

The background term allows a student's ordinary noise floor to differ from
the reference node. The upper residual is the positive 95th percentile of
calibration errors. The initial margin is 25% plus four local ADC RMS counts;
these are prototype defaults, not a validated classroom operating point.
They are defined in `reference_detector_init()` through `reference_config_t`.
This is a small baseline regression plus the existing speech model, rather
than another lecture/conversation classifier.

Above-threshold level alone does not start an alert. At least two of the three
existing overlapping neural contexts must vote for speech, in two consecutive
500 ms windows. Once active, the existing policy holds through one weak window
and releases on the second. `HOLD=1` identifies that brief hold. Invalid,
clipped, stale, repeated or badly aligned readings clear persistence and produce
`UNKNOWN`. Gaps also clear persistence. A valid silent reference does not
disable detection of additional local speech.

Three coughs rejected by the current detector are useful observations, not a
guarantee for every cough. A long cough or another noise misclassified as speech
can still pass the gates. The synthetic transient tests verify duration logic;
they do not evaluate the model on cough audio.
Even without misclassifying the noise itself, loud noise mixed with lecturer
speech can pass, because the mixture can contain valid speech evidence already.

## Networking handoff

The portable API is in `firmware/audio/reference_detector.h` and `.c`:

```c
reference_detector_t student_state;
reference_detector_init(&student_state);
/* Repeatedly, with fresh paired evidence on one common clock: */
reference_result_t result = reference_detector_update(
    &student_state, &lecturer_reading, &student_reading, now_us);
```

Use one state per student. Each reading contains RMS, raw speech votes (0..3),
common-clock time and a validity flag. Only set validity for clean, unclipped,
no-overrun audio. Call from one core/task. Age limit is 1.5 seconds and pair
skew limit is 250 ms. Reinitialize after node reboots or placement/gain changes;
check missing-node timeouts even when no new packet arrives. A downstream
fusion consumer must expire old events rather than latch an alert forever.

The USB command service in `reference_service.c` accepts:

```text
@RESET
@PAIR,node_id,now_us,ref_time_us,ref_rms,ref_votes,ref_valid,student_time_us,student_rms,student_votes,student_valid
```

Node IDs are 1..7 and times are unsigned microseconds on a **common clock**.
It returns `REF_RESULT` with the decision, reason, expected level, threshold
and hold flag. Commands execute on the reference Pico; the PC does not run
neural inference or the final decision in live mode.

The USB bridge estimates a common clock using receipt time minus reported
processing duration and recent minimum transport delay. This permits an initial
demonstration but is not sample-accurate synchronisation or echo cancellation.
The existing UDP v1 packet layout and four-class probability fields remain
unchanged; they must not be silently repurposed for these speech votes. The
networking integration needs an agreed evidence message and shared timestamps.

## Verification and limits

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/verify_reference_detector.py
```

Checks compile the C service with warnings treated as errors, then exercise
calibration, teacher volume changes, transient/noise gates, onset/hold/release,
independent node state, stale/invalid/future/skewed/replayed samples, gaps,
malformed commands, parser recovery and USB clock alignment.

The Pico W firmware build passes: 82,772 bytes of text/read-only data and
90,916 bytes of BSS, with a 4 KiB core-0 stack reservation. These size numbers
are not measured runtime stack/heap peaks. The added service's board timing,
two-node behaviour and classroom accuracy have not been physically measured.
Core 1 remains reserved for the existing VAD frontend.

Movement, different microphone response, amplification and room acoustics can
break a level baseline. Student speech that does not rise sufficiently above
the lecturer baseline can be missed. `STUDENT_TALKING` means sustained excess
speech near that node, not verified speaker identity or intent.
