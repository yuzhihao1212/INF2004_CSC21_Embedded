# Copy this file to node_config.cmake (same folder) and fill it in.
# node_config.cmake is git-ignored: never commit a Wi-Fi password.
# After editing, reconfigure CMake (VS Code: CMake: Delete Cache and Reconfigure).

set(MOSAIC_NODE_ID 1)                  # 1..8, different for every Pico (decision D2)
set(MOSAIC_PC_IP "192.168.1.100")      # IP of the PC running python -m mosaic.gateway (D1)
set(WIFI_SSID "your-network")
set(WIFI_PASSWORD "your-password")     # "" for an open network
