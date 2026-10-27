# INF2004_CSC21_Embedded

MOSAIC: Multimodal Observation and Sensor-fusion Architecture for Intelligent Classrooms.
See [docs/](docs/) for the project brief and team workflow.

## Repository layout

```
firmware/          Pico W firmware (CMake project "mosaic")
  CMakeLists.txt   SDK import and project setup
  tests/           Standalone sensor / DSP bring-up targets, one .uf2 each
ml/                Audio dataset preparation, feature extraction and model training
  scripts/         Run from the repository root, e.g. python ml/scripts/train_pico_model.py
  data/            Feature datasets (raw audio folders are git-ignored)
pc/                PC-side gateway, sensor fusion and dashboard
  mosaic/          Protocol v2, gateway receiver and node simulator
  tests/           Unit tests, run from pc/ with python -m unittest
  prototype/       Early text-format UDP sender/receiver (superseded by mosaic/)
docs/              Project brief and team workflow
```

## Building the firmware

The team uses Raspberry Pi Pico SDK v1.5.1 with `PICO_BOARD=pico_w`.

- **VS Code:** open the repository root. `.vscode/settings.json` already points CMake at
  `firmware/` and builds into `firmware/build/`.
- **Command line:**

  ```
  cmake -S firmware -B firmware/build -G Ninja -DPICO_SDK_PATH=<path to pico-sdk>
  ninja -C firmware/build
  ```

Each target in `firmware/tests/` produces its own `.uf2` in `firmware/build/tests/`.
Never commit `build/` folders; they are git-ignored.

## Python environment

```
python -m venv .venv
pip install -r requirements.txt
```

## Running the PC gateway

From the `pc/` folder (the gateway itself needs only the Python standard library):

```
python -m mosaic.gateway --csv telemetry.csv
```

It listens on UDP 5005, prints each node's readings, and every 10 s prints a table with
each node's status (ONLINE/STALE/OFFLINE), packet loss, reboots and PING round-trip time.
To test without hardware, run the simulated nodes in a second terminal:

```
python -m mosaic.simulator --nodes 3 --loss 0.1 --reboot-every 30
```

On Windows, allow Python through the firewall when asked so real nodes can reach port 5005.

### Live dashboard

```
python -m mosaic.dashboard                 # then open http://localhost:8050
python -m mosaic.dashboard --simulate 3    # rehearse with simulated nodes, no second terminal
```

The dashboard runs the gateway and serves a web page with each node's status, readings,
audio class and link quality, plus CO₂ and temperature trends for the last 1–10 minutes.
A pill in the top bar says whether the data is **Simulated** (sent from this computer),
from real **Sensors**, or **Mixed**; simulated node cards are also tagged.
Add `--http-host 0.0.0.0` to open it from another device on the same network, `--csv FILE`
to log readings, and `--verbose` to also print every packet.

To change a node's settings, POST only the fields you want to change. The gateway then delivers
them as a CONFIG, retrying until the node acknowledges, and resends after the node reboots:

```
curl -d '{"report_interval_ms": 500, "mode": "DISCUSSION"}' http://localhost:8050/api/nodes/1/config
```

Fields and ranges are listed under CONFIG in [docs/protocol.md](docs/protocol.md). The
`config` entry for each node in `/api/state` shows the delivery's progress. There are no
buttons on the page for this yet.

### Classroom states (fusion)

The gateway and dashboard run the fusion engine (`pc/mosaic/fusion.py`, statechart 6.4). It
combines every zone's audio probabilities, PIR motion, CO₂ and temperature/humidity into
three parallel states: **activity** (empty, quiet, focused lecture, discussion, noise rising,
sustained chatter), **air** (normal or poor ventilation) and **comfort**. The page shows them
under *Classroom*, with buttons that switch the classroom mode (Lecture, Discussion, Quiet work)
for fusion and every node at once.

Thresholds, dwell times and the node → zone map are defaults in `FusionConfig`. To tune them
without editing code, pass a JSON file containing only the values to change:

```
python -m mosaic.dashboard --fusion-config fusion.json
```

where `fusion.json` is, for example, `{"co2_poor_ppm": 1500, "zones": {"1": "A", "2": "C"}}`.
`pc/tests/test_fusion.py` holds the scripted scenarios (lecture, chatter, discussion,
ventilation and so on) that check the rules.

To demonstrate the states without hardware, run a scripted classroom:

```
python -m mosaic.dashboard --scenario demo
```

Four simulated nodes play the scenario. The console announces each phase and the state it
should produce, and prints every classroom state change. Scenarios (defined in
`pc/mosaic/scenarios.py`):

| Scenario | Shows | Length |
|----------|-------|--------|
| `lecture` | empty → lecture → rear chatter (noise rising → sustained chatter) → settles | 8 min |
| `discussion` | group work: noise in Lecture mode, **Discussion** if you click that mode | 6 min |
| `ventilation` | CO₂ builds up → poor ventilation → window opened → normal | 6 min |
| `comfort` | air-conditioning fails → out of range → restored | 6 min |
| `exam` | silent, motionless exam stays occupied (PIR is motion, not presence) | 6 min |
| `demo` | all of the above in one run | 18 min |

`pc/tests/test_scenarios.py` plays each one through the fusion engine and fails if a phase no
longer reaches its state, for example after a threshold is changed.

## Contributing

`main` is protected: all changes go through a pull request with passing CI and one approval.
Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for the step-by-step workflow.
