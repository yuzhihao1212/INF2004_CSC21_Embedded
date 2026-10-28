# Recording-only isolation firmware

This build investigates the report that the original code is clean but the
added inference/recording path is noisy. That comparison has not yet been
reproduced here; the exact friend's original code is not available locally.

`firmware/audio/audio_capture.c` is unchanged against repository HEAD
`5bacc88`. The new `audio_talking` target added neural inference, a core-1
frontend worker and USB raw transport. The normal double-buffer capture starts
the next acquisition before processing/transmitting the previous buffer.
Pico/PC score agreement checks inference numerics; it does not rule out
load-induced analogue interference, capture scheduling or playback differences.

The original DSP preprocesses its feature input with DC removal and a high-pass
filter. The diagnostic WAV contains raw ADC audio after block DC removal, and
the separately named amplified WAV boosts existing noise as well as speech.
The model's feature normalisation does not modify the ADC data in that WAV.

## Isolated capture

Flash `firmware/build/audio/audio_record_only.uf2`. Source:
`firmware/audio/audio_record_only.c`. It uses GP26/ADC0, 16 kHz, 8000 samples,
and the same ADC divider/FIFO/DMA settings as the existing sampler. There is no
DSP or classifier and core 1 is not launched. The ADC is stopped before any
raw transport output. USB connection maintenance can still run during capture.

From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' ml/scripts/diagnose_microphone.py --port COM5 --record-only
```

Host recording-only dependencies are NumPy, pyserial and soundfile. It does not
load `frontend_np.py`, `mel_filterbank.npy`, `pulsevad_2.1k.onnx`, `head.json`,
ONNX Runtime, or the classifier. The script collects sixteen blocks and saves
WAVs, exact ADC values and capture/transport metadata in the usual diagnostics
folder. The printed quiet/talk prompts still apply.

There are intentional gaps between the half-second blocks while USB sends
the data. This is an isolation recording, not continuous real-time VAD. Its WAV
concatenates those blocks; use the preserved delivery timestamps to identify
the boundaries. Board model scores are explicitly absent (`-1` in transport,
`null` in metadata); they must not be interpreted as zero speech probability.

Compare `microphone.wav` at the same playback volume and use the amplified
copy only for a separate listening check. A different noise level here helps
isolate the added processing load, but it is not a diagnosis by itself.

Build:

```powershell
& 'C:/Program Files/Raspberry Pi/Pico SDK v1.5.1/cmake/bin/cmake.exe' --build firmware/build --target audio_record_only
```

Host verification in `ml/scripts/verify_microphone_diagnostic.py` covers the
real C encoder, byte-exact sample transport, absent model scores, malformed
recovery, buffered reads, recording with missing model paths and serial cleanup.
On-board comparison still requires the physical setup.
