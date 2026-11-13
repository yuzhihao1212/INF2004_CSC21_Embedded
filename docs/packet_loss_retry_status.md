# Telemetry retry work: validation status

This branch adds two bounded retries for each successfully submitted telemetry
message. Copies retain their sequence, timestamp and payload. The gateway ignores
duplicates and repairs tracked sequence gaps when late messages arrive. This is
application-level recovery; it does not establish a raw Wi-Fi loss rate below 1%.

## Hardware observations, 9 November 2026

Arif flashed the firmware on one Pico W and ran the updated dashboard on a Mac
using home Wi-Fi. In the room, signal reached approximately -78 dBm; connection
attempts also showed authentication, discovery and DHCP failures. Cumulative
gateway loss remained around 13%, with no detected gaps recovered.

Near the router, RSSI was approximately -43 to -45 dBm. Across the supplied
summary interval, received increased from 1188 to 1224 while lost remained 145.
Serial counters increased steadily without additional local send failures in
the supplied interval. Retry submissions and duplicate reception were observed.
Successful local sends do not prove over-the-air delivery.

The cumulative reboot count increased during the session. Saved CSV entries
show sequence and sender uptime resets, but the cause remains unresolved.
The aggregate session includes reconnects and restarts and is not an isolated
passing soak test. N10 remains unpassed; hotspot, two-node operation and sensor
accuracy are not validated by this work.

## Software validation

The integrated firmware builds with local Pico SDK 2.3.0. The full PC suite
previously passed 204 tests after integration with main. Focused regression tests
cover gateway tracking, the C retry scheduler and offline evaluation.

Do not describe this branch as a completed packet-loss or restart fix. Further
work must distinguish radio delivery, power/reset causes and gateway accounting.
Private network configuration, firmware binaries and raw local logs are excluded
from the source commit.
