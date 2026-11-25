# Earlier firmware and shared components

The deployed classroom system uses the [µT-Kernel node](../node/README.md)
with MQTT. This directory preserves the earlier CMake firmware and standalone
bring-up/benchmark targets used for development and comparison.

Keep these files even when building the final node:

- `common/include/mosaic_protocol.h` defines the shared protocol v2 wire layout.
- `audio/` contains the historical DSP/classifier reference, generated tables
  and model provenance used in the current firmware and host checks.
- `tests/` and `tools/fw_budget.py` support standalone validation and resource reporting.
- CI still builds the earlier CMake targets.

The legacy UDP instructions remain here for reproducibility. For the live
four-node demo, use the [root quick start](../README.md).

## Building the earlier CMake firmware (reference)

The code in `firmware/` is what ran before the move to micro T-Kernel. It still builds and
CI still checks it, so each owner can compare while porting. The team built it with
Raspberry Pi Pico SDK v1.5.1 and `PICO_BOARD=pico_w`.

- **VS Code:** open the repository root. `.vscode/settings.json` already points CMake at
  `firmware/` and builds into `firmware/build/`.
- **Command line (from the repository root):**

  ```
  cmake -S firmware -B firmware/build -G Ninja -DPICO_SDK_PATH=<path to pico-sdk>
  ninja -C firmware/build
  ```

Each target in `firmware/tests/` produces its own `.uf2` in `firmware/build/tests/`.
Never commit `build/` folders; they are git-ignored.

## Historical UDP node bring-up

> **Earlier firmware.** These steps are for the CMake node in `firmware/`, which talks UDP.
> The current micro T-Kernel node in `node/` uses the MQTT build and broker described in the [root guide](../README.md). The
> steps below are retained as historical instructions for the earlier firmware.

`firmware/node/` builds `mosaic_node.uf2`: DHT22, CO₂ and PIR readings sent as protocol v2
TELEMETRY every second over Wi-Fi (audio not wired in yet).

1. Copy `firmware/node/node_config.example.cmake` to `firmware/node/node_config.cmake` and set
   the node ID, Wi-Fi name and password, and the PC's IP address (`ipconfig` on Windows,
   `ipconfig getifaddr en0` on macOS). This file is git-ignored; never commit it.
2. Reconfigure and build (VS Code: **CMake: Delete Cache and Reconfigure**, then build), and
   flash `firmware/build/node/mosaic_node.uf2`.
3. From `pc/`, start `python -m mosaic.dashboard` (or `python -m mosaic.gateway`) on the PC. The Pico
   and PC must be on the same network, and the network must allow devices to talk to each
   other (many campus and guest Wi-Fi networks don't; a phone hotspot works).
4. Check the PC can reconfigure the node: run the dashboard with `--verbose`, then send
   `curl -d '{"report_interval_ms": 500}' http://localhost:8050/api/nodes/1/config`
   (use your node ID). The console prints `CONFIG 1 applied` once the node acknowledges.
   The node only accepts CONFIG from the PC IP it was built with.

The onboard LED blinks once per packet sent. Wi-Fi status and the node's IP are printed on
the USB serial port. The node uses the SDK's interrupt-driven background Wi-Fi servicing
(still no FreeRTOS). Receive callbacks validate and copy CONFIG/PING into a four-entry
queue; the main loop applies configuration and sends replies. Foreground lwIP calls are
locked. A full control queue drops the new packet without blocking, so CONFIG retries can
recover. Serial health messages report telemetry send attempts and control-queue drops
every 10 s; a successful send means lwIP accepted it, not that the PC received it.

After flashing, leave the dashboard and USB serial monitor open for a 10-minute run, then
repeat the CONFIG check above while the node is ONLINE. Confirm both the node's
`CONFIG ... applied` message and the gateway's acknowledgement; an HTTP
`config_version` response alone only confirms that the PC queued the update. Record any
CYW43 timeouts or OFFLINE periods. A join or DHCP attempt stuck for 30 s restarts station
mode, and RSSI is queried only while connected, at most once every 5 s.

For unreliable Wi-Fi, each telemetry report has up to two short, bounded retry
copies. The updated gateway deduplicates them and repairs tracked gaps without
counting late copies as reboots or rewinding live readings. Flash and run the
updated node and PC code together. The gateway summary/API exposes recovered
messages, first-observed gaps and duplicates separately. Dashboard loss means
**unrecovered unique messages**, not raw radio loss; raw packet-loss evidence
and the N10 result must still be retained separately. There is no delivery
guarantee during an outage: retry storage is fixed and expires after 600 ms.
