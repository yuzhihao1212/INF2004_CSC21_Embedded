# INF2004_CSC21_Embedded

MOSAIC: Multimodal Observation and Sensor-fusion Architecture for Intelligent Classrooms.
See [docs/](docs/) for the project brief and team workflow.

## Repository layout

```
firmware/          Pico W firmware (CMake project "mosaic")
  CMakeLists.txt   SDK import and project setup
  tests/           Standalone sensor / DSP bring-up targets, one .uf2 each
ml/                Reusable audio capture, DSP and historical experiment tools
  scripts/         Microphone capture and DSP verification tools
pc/                PC-side gateway, sensor fusion and dashboard
  mosaic/          Protocol v1, gateway receiver and node simulator
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

## Contributing

`main` is protected: all changes go through a pull request with passing CI and one approval.
Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for the step-by-step workflow.

## Audio detection direction

The previous lecture/conversation training experiments are retired. Their
recorded and simulated training data, downloaded source audio, trained models,
and evaluation outputs have been removed at the user's request.

Firmware, microphone capture, DSP and their verification tools remain. The old
training, comparison, simulation and evaluation scripts have also been removed.
No trained classroom classifier is active.

The new `audio_talking` firmware integrates pretrained PulseVAD and a locally
trained speech/non-speech head. It emits both model scores and local speech
events over USB. The Pico W build and host numerical checks pass. An optional
lecturer-reference comparison now runs on the reference Pico using a USB bridge
for paired readings. Its simulated C logic tests pass; two-node board timing
and classroom accuracy remain unmeasured. Wi-Fi/fusion integration is pending.

See [speech detector build, run and training instructions](docs/audio_talking_workflow.md).
See [lecturer-reference comparison and demo commands](docs/lecturer_reference_workflow.md).
