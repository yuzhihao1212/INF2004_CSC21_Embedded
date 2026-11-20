# Four-node audio investigation — 20 November 2026

## Scope and provenance

Local `arif/utk-network` base `6123d584438e239ca1f800b76b6ae01b438363c5`
plus uncommitted application, SDK driver, classifier and PC changes. Builds
were made from a dirty tree. The locally cached `origin/main` is `c6a33c8`;
it contains later changes including PR #41's integer-only DSP cleanup. Remote
GitHub branch access could not be verified during this investigation. A bare
commit hash cannot reproduce this session.

## Measured observations

- User-reported quiet, 16:49:12–16:49:42: Node 1 labelled 51/60 windows
  SPEECH; its filtered RMS was 8.875–13.8125 ADC. Other nodes also produced
  speech labels in that quiet interval. This is a mismatch with the reported
  quiet condition, not a complete accuracy measurement.
- Node 1 serial diagnostics after the user unplugged/reconnected the physical
  lecturer Pico recorded repeated 99–100% speech and `clipped=0`. This confirms
  high model scores before the PC for those sampled windows if the room was
  quiet. It does not establish why the input was speech-like.
- The user observed the expected dashboard state for lecturer only, and
  individually for student audio near nodes 2, 3, and 4. Those are single
  setup observations, not classifier accuracy or multi-condition validation.
- During the quiet interval, a 17-ADC PC-only node-1 floor would suppress all
  51 speech-labelled windows. In the earlier lecturer-only interval it would
  also suppress 12 of 44 speech-labelled node-1 windows. These are offline
  window counts, not demonstrated dashboard outcomes.

## Code path and gate scope

The local firmware int8 model produces probabilities on the Pico. Uncommitted
`audio_inference.c` changes make the transmitted SPEECH class follow the
existing two-window timing state. Raw probabilities are retained. The PC
`FusionEngine` and `ReferenceFusion` consume probabilities, including in some
UNKNOWN windows, rather than relying solely on that transmitted class.

The local PC trial config `/tmp/mosaic-node1-quiet-trial.json` sets node 1's
filtered RMS floor to 272 Q12.4 (17 ADC), and node 2's to 80 (5 ADC). For a
below-floor window, `fusion.py` makes a copy for PC fusion whose probability
vector is treated as background; it does not modify MQTT telemetry or the
node's int8 model. Node 1's floor does not apply to student node 3 or 4.

The gate affects the lecturer visual, classroom fusion, calibration (where
lecturer speech probability is checked), and fallback decisions that depend on
whether the lecturer is considered speaking. Correction: after calibration,
the per-window reference comparison uses reference RMS in `_levels()` and
local speech probability; the code does not simply require each reference
window's speech probability to pass the gate. Therefore it is not established
that the node-1 gate caused the calibrated student rows to miss speech. The
earlier claim that the gate necessarily blocks all calibrated rows was too
strong. The trial was removed from the running dashboard; the earlier node-2
floor config was restored.

## Independent timing risk

Serial diagnostics reported approximately 11.7 ms for a nominal 500 ms capture
and roughly 5.6 ms DSP, whereas a temporary timer-startup candidate previously
reported approximately 500 ms capture and 240 ms DSP. The candidate was not
committed. Time-based node quality/deadline and gap checks rely on that clock;
its scale therefore needs verification and correction, not only relabelling
measurements. Shared template/kernel changes require team and instructor
agreement under the project rules.

## Next validation

Keep calibrated node positions fixed. Capture synchronised microphone signal
quality and labelled quiet/normal/soft lecturer audio plus student speech. Verify
PC reference/fusion state and reasons, model inputs, and timing on the actual
build. Preserve raw telemetry, avoid inferring electrical interference or model
accuracy without controlled evidence, and do not commit hotspot credentials.
