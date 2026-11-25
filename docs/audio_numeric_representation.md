# Audio and classifier number formats

How every value in the node's audio path is stored and scaled. Written on
25 Nov 2026 from the source: `node/app_program/subsystem1/` (Moe) and
`node/app_program/subsystem2/` (Darius). No floating point is used anywhere in
this path. "Qn" means the stored integer is the real value times 2^n.

The host replay tests S1-U04, S1-U08 and S2-U03 check this arithmetic against
the reference firmware, bit for bit, on 32 recorded windows.

## Subsystem 1: capture and DSP

| Quantity | Type | Format and range | Where |
|---|---|---|---|
| ADC sample | `uint16_t` | Unsigned 12-bit, 0 to 4095; 16 kHz, 8000 per 500 ms window | `drv_audio.c` |
| Digital gain | `uint16_t` | Q8.8, 256 = 1.0; allowed 26 to 2560 (0.1 to 10.0). Applied about the window mean, result clamped to 0 to 4095 | `task_audio.c` |
| Window mean | `uint32_t` | Q8 ADC counts | `audio_signal_quality.c` |
| AC RMS (quality gate) | `uint32_t` | Q8 ADC counts, integer square root of a 64-bit mean square | `audio_signal_quality.c` |
| Clipped samples | `uint32_t` | Count of samples at 4 or below, or 4091 or above | `audio_signal_quality.c` |
| DC-removed sample | `int32_t` | Q4 ADC counts | `audio_dsp.c` |
| High-pass coefficient | constant | Q15, 31228 = 0.953 (about 125 Hz at 16 kHz); 64-bit accumulator, then `>> 15` | `audio_dsp.c` |
| Frame | `int32_t[400]` | Q4; 25 ms frame, 10 ms hop, 48 frames per window | `audio_dsp.c` |
| Frame RMS | `int32_t` | Q8, from a Q4 integer square root shifted left by 4 | `audio_dsp.c` |
| Hamming window | `int16_t[400]` | Q15, precomputed table | `dsp_tables.h` |
| FFT input | `int16_t[512]` | Each frame is scaled so its peak is 30000, then zero-padded from 400 to 512 | `audio_dsp.c` |
| FFT twiddle factors | `int16_t[256]` | Q15 sine and cosine tables | `dsp_tables.h` |
| FFT | `int16_t` | 512-point radix-2. Every butterfly output is halved, so the result is the true spectrum divided by 512 and cannot overflow | `audio_dsp.c` |
| Power spectrum | `uint32_t[257]` | `re*re + im*im`, at most 2^31 | `audio_dsp.c` |
| Spectral centroid | `int32_t` | Q8 hertz; bins 4 to 240 (125 Hz to 7.5 kHz) | `audio_dsp.c` |
| Band-energy ratios | `int32_t` | Q8, 0 to 256 = 0 to 1. Low: bins 4 to 15; mid: 16 to 63; high: 64 to 240 | `audio_dsp.c` |
| Mel filter weights | `int16_t[20][257]` | Q15, precomputed; 64-bit sum, then `>> 15` | `dsp_tables.h` |
| Log mel energy | `int32_t` | Natural logarithm in Q12; zero energy maps to a floor of -24 | `audio_dsp.c` |
| DCT table | `int16_t[5][20]` | Q14, precomputed | `dsp_tables.h` |
| MFCC 1 to 5 | `int32_t` | Q8: Q12 times Q14 summed in 64 bits, then `>> 18` | `audio_dsp.c` |
| Feature vector | `int32_t[20]` | Q8. Mean, then standard deviation, of the 10 frame features over 48 frames | `audio_features.h` |

The ten frame features are: RMS, spectral centroid, low, mid and high band
ratios, and MFCC 1 to 5.

Rounding: every shift and integer division truncates. The standard deviation is
an integer square root of a variance clamped at zero.

## Subsystem 2: int8 classifier

A fully connected network, 20 inputs, 16 hidden units, 3 outputs. Weights are
`int8_t` (320 + 48 = 368 bytes); biases are `int32_t`. All zero points are 0:
the quantisation is symmetric.

| Step | Arithmetic | Result |
|---|---|---|
| Input scaling | `(feature_q8 - mean[i]) * mult[i]`, rounded and shifted right by 16 | `int8_t`, clamped to -128 to 127 |
| Hidden layer | `b1[j] + sum(input[i] * w1[j][i])` in `int32_t`, times 72784, rounded and shifted right by 24 | `int8_t`, clamped to 0 to 127 (ReLU) |
| Output layer | `b2[k] + sum(hidden[j] * w2[k][j])` | `int32_t` logits |
| Softmax | Distance below the largest logit, times 1579172, rounded and shifted right by 24, indexes a 513-entry table of `32768 * exp(-i/32)` | Q15 probabilities that sum to exactly 32768 |

- **Scales.** `mean[]` and `mult[]` hold one offset and one Q16 multiplier per
  feature. The hidden layer's rescale is 72784 / 2^24. One softmax table step
  (1/32 in natural-log units) is about 10.6 logit units.
- **Rounding.** Half away from zero, in 64-bit intermediates.
- **Overflow.** The largest possible hidden sum is 20 x 128 x 127 plus the
  largest bias, about 330,000. The largest output sum is 16 x 127 x 127 plus
  the bias, about 259,000. Both are far inside `int32_t`.
- **Classes.** 0 background, 1 speech, 2 transient.

## Gates and the wire format

| Quantity | Format | Rule |
|---|---|---|
| Low-level gate | AC RMS, Q8 | Below 4 ADC counts (1024 in Q8): no label |
| Clipping gate | Sample count | 80 or more of 8000 samples (1%) at a rail: no label |
| Speech persistence | Q15 probability | Speech must win with at least 16384 (0.5) in two consecutive windows |
| Confidence threshold | Percent, from CONFIG | Compared as `p * 100 >= threshold * 32768`, with no division |
| Wire loudness `rms_x16` | `uint16_t`, Q12.4 | Mean frame RMS from Q8, rounded: `(rms + 8) / 16`, saturating at 65535 |
| Wire probabilities | `uint8_t[4]`, percent | `p * 100 / 32768`, truncated. Slot 3 is reserved and 0; transient takes the remainder so the sum is exactly 100 |

## Known limitation

Durations in this path (`capture_us`, `dsp_us`, `ml_us` and the telemetry fields
`dsp_time_us` and `inference_time_us`) are raw timer counts. On this kernel one
count is 42.67 µs, not 1 µs, so each value must be multiplied by 42.67 to give
real time. See the note above `audio_clock_us()` in `drv_audio.c`.
