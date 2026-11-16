# Audio / ML on micro T-Kernel

S1's `audio_task` owns GP26/ADC0 and DMA. It runs on core 0, priority 13,
with a 4096-byte stack. The driver uses DMA IRQ1 through `tk_def_int` and
a completion semaphore. It never uses SDK IRQ vector installation.

The original capture behavior is preserved: ADC stops after each 8000-sample
window, and the task rearms the alternate buffer before processing the completed
buffer. This is not a guarantee of gapless capture; check timing on the board.
Completed raw buffers are never shared with ML and cannot be overwritten until
S1 next calls the driver. Timeouts and queue rejection leave sequence gaps.

The DSP processing maths and feature order are preserved. Startup tables are
generated once on the host into `dsp_tables.h`, removing runtime libm dependencies.
Regenerate using `py node/testing/subsystem1/generate_dsp.py`. The original
standalone implementation remains under `firmware/audio/` as a reference.

S2's classifier task runs on core 1 at priority 15 (core 0 under SMP=0).
It receives copied feature records through a two-message buffer owned by S2.
Queue sends never block S1. S2 resets speech persistence at sequence gaps,
counts missing observations, and is the only task posting audio to S5, so old
queued features cannot race ahead of loss accounting.

The classifier files in S2 retain the original int8 weights, integer activations,
Q15 probabilities and timing rules. The original model provenance is
`firmware/audio/classifier/SOURCE.json`. No training runs on the node.
Protocol class IDs are 1/2/4, not the model's 0/1/2; reserved probability slot
2 stays zero. Telemetry RMS is feature 0's mean frame RMS, converted Q8 to Q4;
the raw AC RMS is used only for quality gates. Local TALKING is a persistence
diagnostic, not a lecturer-versus-student identification.

S1 reads S5's CONFIG snapshot; gain defaults to unity and is applied around the
window mean before quality checks/DSP. S2 applies the confidence threshold and
marks clipped, low-level and late windows UNKNOWN. Capture completion timestamps
and separate DSP/ML durations are in microseconds. Debug lines are integer-only
and rate-limited in S2, away from capture.

The existing LED and producer examples remain active for compatibility with
S3/S4's existing references and tests. S4 can still suspend the LED, never the
new audio task. Their eventual cleanup belongs to their respective owners.
S1/S2 make no networking calls and do not launch cores manually. S5 already
accepts audio results; the network owner must connect its TX queue to MQTT
inside `cyw43_utk_task` for end-to-end delivery.

Build with the template's Pico SDK 2.2.0/2.3.0 setup:

```sh
cd node/build_make
make -j8
# With configured MQTT broker/Wi-Fi and the network owner's bridge:
make NET=lwip MQTT=1 -j8
```

Default artifact: `mtk3pico_smp1_usb_cdc_wifi.uf2`. Test definitions and logs
live in `node/testing/subsystem1/` and `subsystem2/`. Cross-building and host
replay do not establish real microphone timing or MQTT delivery.

Validated locally: USB/Wi-Fi and MQTT profiles link against SDK 2.2.0; host
replay matches all 20 reference DSP outputs and the reference classifier.
The private `node/config/wifi_secrets.h` is absent. The MQTT compile check
used the public example via an ignored build include directory, so that
MQTT image has placeholder settings and is not a configured deployment.
The default USB/Wi-Fi UF2 is suitable for the next bench test of audio output.
