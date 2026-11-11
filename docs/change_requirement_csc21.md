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

| Evidence | Scope | Owner | Status |
|----------|-------|-------|--------|
| Numeric representation table | Wire formats | Arif, ZhiHao | Done: `docs/protocol.md` (`_x10`, Q12.4, Q8.8) |
| | Acoustic DSP Q-formats | Moe | To do |
| | int8 model scales and zero points | Darius | To do |
| | Environmental and occupancy conversions | Kendrick | To do (`environment.h` documents the units) |
| | Node-health calculations | Arif | Representation and limits recorded in `node_health_numeric_representation.md`; host tests cover watchdog gating and audio handoff. CPU load remains unmeasured; linked-firmware float audit and end-to-end timing remain pending. |
| | Sensor-fusion mathematics | ZhiHao | To do (fusion is being made integer-only) |
| DSP timing with headroom (500 ms budget) | Complete DSP path on the Pico | Moe | To do (Week 10 test B2) |
| Accuracy comparison: fixed-point DSP vs float | Feature outputs | Moe | To do (the float version is in git history) |
| Accuracy comparison: int8 vs float inference | Classifier | Darius | To do |
| Accuracy comparison: integer vs float fusion | Classroom states | ZhiHao | To do |
| No floats in application paths | Build check (soft-float helpers in the `.elf`) and PC fusion check | All | To do |
| Correctness and performance within a stated margin | End-to-end scenarios | All | To do (evaluation script + Week 11 runs) |
