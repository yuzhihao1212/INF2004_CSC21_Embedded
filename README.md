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

## Running a real node

`firmware/node/` builds `mosaic_node.uf2`: DHT22, CO₂ and PIR readings sent as protocol v1
TELEMETRY every second over Wi-Fi (audio not wired in yet).

1. Copy `firmware/node/node_config.example.cmake` to `firmware/node/node_config.cmake` and set
   the node ID, Wi-Fi name and password, and the PC's IP address (`ipconfig` on Windows,
   `ipconfig getifaddr en0` on macOS). This file is git-ignored; never commit it.
2. Reconfigure and build (VS Code: **CMake: Delete Cache and Reconfigure**, then build), and
   flash `firmware/build/node/mosaic_node.uf2`.
3. Start `python -m mosaic.dashboard` (or `python -m mosaic.gateway`) on the PC. The Pico
   and PC must be on the same network, and the network must allow devices to talk to each
   other (many campus and guest Wi-Fi networks don't; a phone hotspot works).

The onboard LED blinks once per packet sent. Wi-Fi status and the node's IP are printed on
the USB serial port.

## Contributing

`main` is protected: all changes go through a pull request with passing CI and one approval.
Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for the step-by-step workflow.
