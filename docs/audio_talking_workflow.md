# Pico neural speech detector and local training

Current microphone wiring is **AUD -> GP26 / ADC0 (physical pin 31)**,
VCC -> 3V3 and GND -> GND. The GP27 trial was reported worse and reverted.

The old lecture/conversation classifier is retired. This target detects local
speech presence. It does not identify a speaker or send UDP/fusion messages yet.
An optional lecturer-reference comparison is now available through a USB bridge;
see [lecturer and student node workflow](lecturer_reference_workflow.md).

## What was added

- Pretrained PulseVAD, pinned to commit
  `af25e79d66830a3fee74541812721f6158fc92b5` from
  <https://github.com/AydinAdnan/PulseVAD> (MIT).
- A portable C frontend (Q24 FFT, Q30 twiddles, FP32 mel/normalisation) and
  complete FP32 neural inference implementation.
  The upstream C weights header omits biases; we instead export the complete
  FP32 ONNX model. This build does **not** use integer-only inference or the
  advertised 2.1 KB INT8 weight payload.
- A genuinely locally trained 9-parameter logistic speech/non-speech head on
  the frozen neural network's eight pooled features. The PulseVAD backbone is
  pretrained; we did not train that network from scratch or fine-tune it.
- Both pretrained and local-head probabilities appear over USB. A positive
  output is called `TALKING`, meaning local speech evidence only.

## Build and run

From the repository root:

```powershell
& 'C:/Program Files/Raspberry Pi/Pico SDK v1.5.1/cmake/bin/cmake.exe' --build firmware/build --target audio_talking
```

Hold BOOTSEL while connecting the Pico and copy
`firmware/build/audio/audio_talking.uf2` to its USB drive. Microphone AUD is on
GP26 / ADC0, with the existing 3V3 and GND wiring.

Close other serial monitors and capture scripts. From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m serial.tools.miniterm COM5 115200
```

The port can change after flashing. List it if needed:

```powershell
& '.\.venv\Scripts\python.exe' -m serial.tools.list_ports
```

Exit miniterm with **Ctrl+]**. The old `capture_audio_sequences.py` and CSV
capture scripts expect different firmware output and should not be used here.

## Live speech detection with WAV playback

Flash the current `audio_talking.uf2` (`timing-v7`) once. To display decisions
and save audio from the SAME session, run this instead of miniterm:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/monitor_speech.py --port COM5
```

Speak normally and press **Ctrl+C** when done. There are no quiet/talking
prompts or eight-second cutoff. The script prints the WAV path at the start
and on exit. Files are saved under
`ml/diagnostics/speech_sessions/<UTC timestamp>/`:

- `microphone.wav`: the exact ADC windows used by the detector, with lossless
  fixed conversion `(ADC-2048)*16` to 16-bit mono PCM at 16 kHz. No per-block
  normalisation, denoising or peak amplification is applied.
- `events.jsonl`: the live model scores, speech events, hold and timing flags.
- `audio_windows.jsonl`: window IDs/timestamps mapped to WAV sample positions.
- `recording_report.json`: received/lost blocks and packet validation counts.

An optional `--seconds 30` ends after 30 seconds of host wall time. Closing
normally or pressing Ctrl+C finalises the WAV header, disables streaming and
releases the serial port. Close any other serial monitor first. Miniterm still
displays scores only and does not record audio.

Streaming is enabled only by the new monitor's `s` command. Each 8000-sample
ADC buffer is losslessly packed into 12,000 binary bytes with a sample-sum
check, followed by the VAD result with the same window ID. Serial newline
translation is disabled on this target so binary bytes are preserved. The
`v` command stops streaming. Existing `r` diagnostic capture is retained.

`TX_US` measures audio transport and `WORK_US` includes inference and audio
transport. `OVERRUN` now uses that total work against the same 500 ms budget;
faults still suppress speech events. The VAD text line itself follows this
measurement. Streaming timing on the physical Pico needs confirmation: the
previous non-streaming build had only about 30 ms headroom. Watch `OVERRUN`.

Invalid audio packets are discarded; missing window IDs are filled with
silence in the WAV and logged, rather than silently shortening the recording.
Delivery-time discontinuities are also logged. Delivery timestamps are not
sample-start timestamps, so overrun gaps cannot be reconstructed exactly.
Incomplete final packets on Ctrl+C are omitted. Newline/byte fragmentation,
the actual C packing, checksum rejection, WAV/event alignment and stop cleanup
are covered by `ml/scripts/verify_speech_recording.py` host tests. Physical
timing and audible recording quality remain board checks.

## Diagnose missed speech

The user confirmed that they were speaking during the supplied `timing-v3`
excerpt, which contained only `NO_SPEECH`. Those are false negatives; timing
success did not establish detection success. The cause has not been identified.

`timing-v4` retains the same model and event thresholds and adds an optional,
eight-second raw microphone diagnostic. Reflash the current
`firmware/build/audio/audio_talking.uf2`, close miniterm/Serial Monitor, and run
from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/diagnose_microphone.py --port COM5
```

Keep quiet for two seconds, then repeat a short sentence normally for six
seconds when the script prints `TALK NOW`. The microphone should remain in the
same position. The script stops automatically, releases COM5 and returns the
board to normal VAD mode. Ctrl+C also requests a return to VAD.

The script reads USB serial in buffered batches and prints the number of
complete audio blocks received. `TALK NOW` appears after block 4 of 16. If the
Pico acknowledges capture but blocks fail validation, a status line reports
received bytes, headers, chunks and the latest parser error every second.
`transport_report.json` is saved even if no complete audio block arrives.
This host-reader update works with the existing `timing-v4` firmware and
does not require another flash.

Results are stored locally under `ml/diagnostics/microphone/<UTC timestamp>/`:

- `microphone.wav`: DC-centred microphone audio at the original ADC scale.
- `microphone_listen_amplified.wav`: peak-amplified copy for listening only.
- `raw_adc.npz`: exact 12-bit samples, window IDs and delivery timestamps.
- `scores.csv`: Pico and upstream-PC scores for the same first 200 ms context
  of each block, plus signal level, clipping and coarse spectral diagnostics.
- `report.json`: score differences and instructed quiet/talking summaries.
- `transport_report.json`: byte/packet counts and parsing errors, including
  captures with zero usable audio blocks.

Raw transport temporarily replaces event output. It uses 16 half-second
packets, ordered 128-sample hex chunks and sample-sum validation. Corrupt or
incomplete packets are rejected. The diagnostic does not train a model or
calculate accuracy from the instructed phases. The actual audible contents
and the board/PC comparison need inspection before changing thresholds or
blaming hardware. Captures are ignored by Git.

Run `ml/scripts/verify_microphone_diagnostic.py` to check the real C encoder
against the Python parser, malformed-packet recovery, upstream replay and
CLI cleanup on Ctrl+C, without hardware.

Every 500 ms block reports `PULSE_PROB`, `OWN_PROB`, `SPEECH_VOTES`, `EVENT`,
`RMS_ADC`, `PROCESSING_US`, `OVERRUN` and clipping metadata. `DELIVERED_US` is
the board's time when a complete block is delivered, not a synchronised
sample-start timestamp. Each probability is the mean over three overlapping
200 ms contexts at offsets 0, 150 and 300 ms; the votes use each context's
individual probability at a threshold of 0.5.

The current `BUILD=timing-v7` output also reports `FRONTEND_US` and
`NETWORK_US`, summed across the three contexts. `PREP_US` measures waveform
preprocessing, `FFT_MEL_US` measures the parallel spectral stage's wall time,
and `ZNORM_US` measures per-band normalisation, each summed over the contexts.
These sub-stages exclude ADC-to-waveform conversion included in `FRONTEND_US`.
The original floating-point
FFT build was measured by the user at approximately 1,386,000 us per 500 ms
block and correctly emitted `TIMING_FAULT`. The updated build moves the FFT
butterflies to fixed point, hoists repeated divisions, and specialises the
convolutions. The user measured `timing-v2` at approximately 647,000 us:
497,000 us frontend and 144,000 us neural inference. `timing-v3` splits the
21 spectral frames between core 0 (11 frames) and core 1 (10 frames), using
independent FFT scratch and explicit completion synchronisation. It retains
all three contexts per audio block. On 2026-10-26, the user supplied 17 `timing-v3` blocks taking 468,055-470,080 us,
all with `OVERRUN=0` and delivery intervals of 500,000 +/- 1 us. That leaves
about 30 ms of processing headroom in this excerpt, without networking/fusion.
All events were `NO_SPEECH`; the user subsequently confirmed they were speaking,
so that excerpt demonstrates missed speech. Keep the
500,000 us overrun limit; do not increase it to conceal lost audio coverage.

At least two positive votes in each of two consecutive valid 500 ms blocks
are required to start `TALKING`. Once active, one weak block is bridged and
reports `TALKING,HOLD=1`; a second consecutive weak block ends the event.
Strong evidence during the hold resumes `TALKING,HOLD=0` immediately.
This prevents one confidence dip from restarting the onset sequence and adds
one block of release delay. Raw probabilities/votes are not changed. It is a
heuristic persistence rule, not proof of uninterrupted speech. Other events are `NO_SPEECH`,
`SPEECH_PENDING`, `LOW_LEVEL`, `CLIPPED`, `TIMING_FAULT` and `INVALID_SIGNAL`.
The provisional low-level gate is 4 AC ADC counts; it is not calibrated SPL.
At least 1% near-rail samples invalidate a block. Processing over 500 ms or
a delivery interval over 750 ms resets persistence and suppresses `TALKING`.

The default decision model is selected by validation results only. Both
models tied on validation, so the initial build uses pretrained PulseVAD;
the locally trained head is compiled in and its score is still shown.

## Reproduce local training

Install host-only requirements into the Python environment:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r ml/requirements-vad.txt
& '.\.venv\Scripts\python.exe' ml/scripts/fetch_vad_audio.py
& '.\.venv\Scripts\python.exe' ml/scripts/train_talking_head.py
& '.\.venv\Scripts\python.exe' ml/scripts/verify_pulsevad.py
```

Rebuild the firmware after training. The head is exported into
`firmware/audio/pulsevad/talking_head.h`; training parameters, source split,
metrics and feature cache are in `ml/candidates/talking_head/`. Source audio
and its hash manifest are in `ml/data/vad_public/`. No old deleted classroom
recordings were restored or reused.

The experiment downloads 180 short spoken-digit recordings from FSDD and
100 environmental recordings from ESC-50. The labels are **speech versus
non-speech**, not lecture versus conversation. Negative examples are needed
even though the only positive event of interest is talking. We also include
synthetic silence/noise negatives. Public speech clips have trimmed utterance
labels; individual 200 ms frames are not manually annotated.

Training speakers are Jackson, Nicolas and Theo; validation uses Yweweler;
testing uses George and Lucas. ESC folds 1-2 train, fold 3 validates, and
folds 4-5 test. Original ESC source IDs cannot cross these partitions. Gain
augmentation is applied to training only. The three regularisation settings
are selected using source-balanced validation accuracy, with equal class and
source weights. The test is scored after selection. Upstream pretrained
training exposure to these sources is unknown, so this is not a wholly
unseen evaluation of the pretrained backbone.

Initial public-subset test results (318 contexts):

| Model | Accuracy | Source-balanced accuracy |
| --- | ---: | ---: |
| Pretrained PulseVAD | 91.82% | 88.93% |
| Locally trained head | 92.45% | 90.62% |

These are host speech-presence results on a small public subset. They do not
measure classroom conversation, physical microphone behaviour, lecturer
rejection, or the live persistence/quality policy.

## Verification and resource limits

The host checks compare the frontend to upstream NumPy and the neural logits
to upstream ONNX Runtime on fifteen generated signals plus one context from
each of the 280 downloaded public recordings when available. Maximum frontend
error after the Q24 optimisation: 0.004349; maximum network logit error on
identical features: 0.000002504. Maximum end-to-end logit error is 0.000251,
with no upstream classification disagreements on these 295 contexts.
The local head's C probabilities agree with Python within 0.000000086.
Host checks also run the two frontend frame ranges concurrently, with
bit-identical features to the sequential implementation on all 295 contexts.
The Pico FIFO/startup synchronisation itself still requires a board check.
Policy checks cover pending/confirmed speech, silence reset, clipping, gaps,
low signal and invalid inputs. These are numerical and logic tests.
They also cover bridging one weak block, resumption without onset delay,
release after two weak blocks and immediate reset on quality/timing faults.
Replaying the supplied 39-block session through the C policy keeps windows
33 and 35 active with `HOLD=1`; that is a policy check, not new accuracy data.

The `timing-v7` Pico W build uses 82,772 bytes of text/read-only data and 90,916
bytes of static RAM according to `arm-none-eabi-size`. Static RAM excludes
stack/heap peaks and future Wi-Fi/fusion additions. The detector uses static
workspaces and a single public caller on core 0. Core 1 and its inter-core
FIFO are reserved by this standalone detector; future sensor/fusion code must
respect that ownership. Call `pulsevad_init()` before microphone capture.
RP2040 has no hardware floating-point unit;
the observed `timing-v3` speed is documented above. Continue checking `PROCESSING_US` and `OVERRUN` on the
physical board before treating this as a real-time detector.

To regenerate the vendor export, clone PulseVAD, check out the pinned commit,
then run `ml/scripts/export_pulsevad.py --upstream <checkout>`. The exporter
checks the commit and expected tensor dimensions. Vendor hashes and licence
are retained under `firmware/audio/pulsevad/vendor/`.

## Data attribution

- [Free Spoken Digit Dataset](https://github.com/Jakobovski/free-spoken-digit-dataset):
  Zohar Jackson and contributors, CC BY-SA 4.0. Downloaded repository commit
  and individual hashes are retained in the dataset manifest.
- [ESC-50](https://github.com/karolpiczak/ESC-50): Karol J. Piczak and original
  Freesound contributors, CC BY-NC; per-recording attribution is retained in
  `ml/data/vad_public/ESC50_LICENSE`. This training subset includes material
  outside the CC BY ESC-10 subset; it is for non-commercial research/coursework.

Dataset licences are separate from PulseVAD's MIT code licence. Preserve the
downloaded credits and review the terms before distributing audio or trained
derivatives outside this coursework.
