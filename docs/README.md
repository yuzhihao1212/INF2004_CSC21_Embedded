# Assessment documentation and evidence

Use this index for final submission. The original plans, decisions and test
results are retained with their dates. Some early documents describe the earlier
CMake/UDP design or work that was pending when written. The current node uses
µT-Kernel with MQTT, as described in the [main README](../README.md).

## Requirements and design

- [Project brief](INF2004_Embedded%20System%20Project%20%28Revised%29.pdf)
- [CSC21 change requirement and evidence tracker](change_requirement_csc21.md)
- [Audio and classifier number formats](audio_numeric_representation.md)
- [How MOSAIC decides what the room is doing](room-states.md)
- [Decision log](decision-log.md)
- [Wire protocol v2](protocol.md) — the MQTT subsection is the active transport;
  the UDP sections describe the earlier firmware. The older S4 README
  also describes the bridge integration step; the calls are now connected
  in the active MQTT service linked below.
- [Team ownership, pins and RTOS interfaces](../node/TEAM.md)
- [Fault table](fault_table.md) — useful historical design review. Cross-check
  old implementation statuses against the current source and evidence below.
- [UI design](ui_design.md)

## Subsystem evidence

| Subsystem | Source or numerical representation | Recorded evidence |
| --- | --- | --- |
| S1 Audio and DSP | [Audio port notes](../node/app_program/subsystem1/AUDIO_PORT.md) | [Replay and integer audit](../node/testing/subsystem1/PORT_TEST_LOG.md), [audio investigation](../node/testing/integration/logs/2026-11-20-audio-investigation.md) |
| S2 TinyML | [Classifier code](../node/app_program/subsystem2/) | [Classifier port tests](../node/testing/subsystem2/PORT_TEST_LOG.md) |
| S3 Sensors | [Integer sensor representation](environment_numeric_representation.md) | [Sensor tests](../node/testing/subsystem3/TEST_LOG.md), [hardware test procedure](../node/testing/subsystem3/HARDWARE_EVIDENCE.md) |
| S4 Networking and health | [MQTT bridge](../node/lib/liblwip/sysdepend/pico_rp2040/mqtt_utk.c), [health representation](node_health_numeric_representation.md) | [S4 tests](../node/testing/subsystem4/TEST_LOG.md), [four-node telemetry session](../node/testing/integration/logs/2026-11-20-four-node-session.md) |
| S5 Telemetry and fusion | [Protocol](protocol.md), [integer fusion](fusion_numeric_representation.md) | [S5 tests](../node/testing/subsystem5/TEST_LOG.md), [PC tests](../pc/tests/) |

## Integration and submission checklist

- [Week 10 test plan](week10_test_plan.md) and [Week 13 evidence plan](evidence_plan_week13.md)
- [Recorded integration cases](../node/testing/integration/TEST_LOG.md),
  [system tests](../node/testing/system/TEST_LOG.md) and [validation notes](integration_validation.md)
- [Resource budget](resource_budget.md) and
  [recorded SDK 2.3.0 measurements](evidence/firmware-budget/local-sdk-2.3.0.md)
- [Evaluation method and metric definitions](evaluation.md)
- [Dashboard and real-node screenshots](evidence/)

The 16–17 November host comparisons established identical features on 32
deterministic audio windows and an integer-only audio/ML object audit. The four
Pico trial on 20 November recorded real audio telemetry but used a working tree
with uncommitted changes. Its logs report a timing scale issue and no valid
temperature, humidity or CO₂ readings at the dashboard; it is an integration
observation rather than complete hardware acceptance.

The final demo on 25 November is recorded in the
[system test log](../node/testing/system/TEST_LOG.md): five scenarios shown on
four Picos, mostly as expected with some inconsistent results, and no recording.
The host tests were rerun on the hand-in code with
`node/testing/run_host_tests.sh`; each subsystem's log cites that commit.

The hardware was returned after the demo. These were never measured and cannot
be now: DSP and inference wall-clock time with headroom on a board, sensor
readings against a reference instrument, fault injection and recovery, and the
watchdog's timing tests. Original test results are kept as they were. The
[test guide](../node/testing/README.md) describes the recording workflow.
