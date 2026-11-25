# CSC21 Change Requirement: Fixed-Point DSP and Integer TinyML

Our assigned change requirement, copied word for word from the course's *Change Requirement 2*
document so the team can check work against it. The evidence tracker below is ours.

---

> **CSC21 – Change Requirement: Fixed-Point DSP and Integer TinyML**
>
> The MOSAIC firmware must use fixed-point or integer mathematics for application-level signal
> processing and inference. Acoustic DSP must use an appropriate fixed-point representation
> selected and justified by the team, while TinyML inference must use an integer-quantised model.
>
> The requirement applies throughout the system, including:
> - acoustic DSP;
> - TinyML inference;
> - environmental-sensor conversions;
> - occupancy-sensor conversions;
> - node-health calculations; and
> - sensor-fusion mathematics.
>
> Teams must select and document appropriate scaling, range, precision, rounding, saturation and
> overflow behaviour. Floating-point arithmetic must not remain in the affected application
> processing paths.
>
> **Week 13 Documentation and Demonstration**
>
> As part of the Week 13 final submission, the team must include the following evidence and
> documentation in its GitHub repository:
> - **Numeric representation table:** Identify the relevant values, their ranges, fixed-point or
>   integer representation, scaling and overflow behaviour.
> - **DSP timing:** Measure the complete DSP processing time and demonstrate that it meets the
>   500 ms budget with stated headroom.
> - **Accuracy comparison:** Compare the fixed-point DSP and int8 inference results against the
>   original floating-point implementation.
> - **Correctness and performance:** Demonstrate that system accuracy remains within a stated and
>   justified margin.

---

## Evidence tracker (Week 13, in this repo)

Status at hand-in, 25 Nov 2026. The hardware was returned after the final demo, so
rows that need a board are marked **Not done** with what exists in their place.

| Evidence | Scope | Owner | Status |
|----------|-------|-------|--------|
| Numeric representation table | Wire formats | Arif, ZhiHao | Done: `docs/protocol.md` (`_x10`, Q12.4, Q8.8) |
| | Acoustic DSP Q-formats | Moe | Done: `docs/audio_numeric_representation.md`, written from `audio_dsp.c` (type, Q-format, range and rounding of every DSP quantity) |
| | int8 model scales and zero points | Darius | Done: `docs/audio_numeric_representation.md`, written from `dsp_int8_candidate.c`. Symmetric int8, so every zero point is 0; one offset and Q16 multiplier per input, hidden rescale 72784 / 2^24 |
| | Environmental and occupancy conversions | Kendrick | Representation, scaling, limits and invalid handling documented in `docs/environment_numeric_representation.md`; host checks cover the conversions. B4/N3 hardware measurements and integrated evidence remain pending. |
| | Node-health calculations | Arif | Representation and limits recorded in `node_health_numeric_representation.md`; host tests cover watchdog gating and audio handoff. CPU load remains unmeasured; linked-firmware float audit and end-to-end timing remain pending. |
| | Sensor-fusion mathematics | ZhiHao | Done: `docs/fusion_numeric_representation.md` (ranges, scaling, rounding, overflow for every fusion and reference quantity) |
| DSP timing with headroom (500 ms budget) | Complete DSP path on the Pico | Moe | **Not done** as a measured test. What exists: the 20 Nov four-node serial log shows `dsp_us` of 5575 to 5591 timer counts with Wi-Fi on. At the node clock's 42.67 µs per count that is about 238 ms of the 500 ms window. The clock scale is a documented limitation (`drv_audio.c`), so this is an estimate, not a calibrated result |
| Accuracy comparison: fixed-point DSP vs float | Feature outputs | Moe | **Not done** against the float version (still only in git history). What exists: S1-U04 and S1-U08 show the node's DSP gives the same 20 features as the reference firmware's DSP, bit for bit, on 32 windows |
| Accuracy comparison: int8 vs float inference | Classifier | Darius | **Not done**: no float version of the model, and no training script for it, is in the repo (`ml/README.md`). What exists: S2-U03 shows the node's int8 inference gives the same logits, class and probabilities as the reference int8 implementation |
| Accuracy comparison: integer vs float fusion | Classroom states | ZhiHao | Done on simulated scenarios: `pc/tests/test_integer_accuracy.py` replays every scenario (seeds 1, 2, 7) through integer fusion and the frozen float version. Margin: same state sequence, each transition within 1000 ms. Result (14 Nov): same sequence; activity 93 transitions, max 500 ms apart; air and comfort 36 each, max under 1 ms. Real-room data not yet compared. |
| No floats in application paths | Build check (soft-float helpers in the `.elf`) and PC fusion check | All | PC fusion done: `pc/tests/test_integer_enforcement.py` fails on any float operation in `fusion.py`/`reference.py` (only `seconds_to_ms` allowed, at the input boundary). Firmware check: `firmware/tools/fw_budget.py` lists every float call in our object files on each CI run. Node, classifier and `audio_dsp_process` have none; `audio_dsp_init` built integer tables with float maths once at start-up (`docs/resource_budget.md`); the tables are now constants in `dsp_tables.h` and it does nothing. With audio linked into the node: S1-U08 (17 Nov) found no float or libm references in the S1 and S2 objects of the kernel build. |
| Correctness and performance within a stated margin | End-to-end scenarios | All | **Not done** on hardware: no labelled run on the four nodes was scored. What exists: the evaluation script (`pc/mosaic/evaluate.py`, `docs/evaluation.md`), the simulated-scenario comparison in the row above, and the final demo, recorded in `node/testing/system/TEST_LOG.md` |
