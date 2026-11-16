# Audio port test cases and results

Test cases are defined before execution. Original example tests/results stay intact.

| ID | Method | Expected result |
|---|---|---|
| S1-U04 | `py node/testing/subsystem1/test_audio_port.py` compiles actual C reference and migrated implementations | Exact equality of 20 Q8 features across 32 deterministic raw ADC windows |
| S1-U05 | Cross-build SMP=1, USB console, Wi-Fi profile; inspect port objects with `nm` | UF2 links; no floating-point runtime references from audio/ML objects |
| S1-U06 | Hardware GP26 microphone, 60 s capture with Wi-Fi traffic | 16 kHz acquisition, roughly 120 windows, no hangs; record actual gaps, drops and maximum DSP duration |
| S1-U07 | Hardware stalled classifier / saturated feature queue | Capture does not block on queue; dropped windows counted; state recovers |

## Results

| Date | ID | Commit | Result | Evidence |
|---|---|---|---|---|

S1-U06/U07 are NOT RUN until real-board evidence is saved.
