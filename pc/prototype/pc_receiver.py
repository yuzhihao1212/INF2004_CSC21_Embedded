import socket
import time

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5005
NODE_TIMEOUT_SECONDS = 5

last_seen = {}

def parse_message(message):
    data = {}

    parts = message.strip().split(",")
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    return data

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening for MOSAIC node data on UDP port {LISTEN_PORT}...")

while True:
    message, address = sock.recvfrom(1024)
    message = message.decode("utf-8")

    data = parse_message(message)

    node_id = data.get("NODE", "unknown")
    zone_id = data.get("ZONE", "unknown")

    last_seen[node_id] = time.time()

    print("\nReceived packet")
    print(f"From address : {address}")
    print(f"Node         : {node_id}")
    print(f"Zone         : {zone_id}")
    print(f"Temperature  : {data.get('TEMP')} C")
    print(f"Humidity     : {data.get('HUM')} %")
    print(f"CO2          : {data.get('CO2')} ppm")
    print(f"PIR          : {data.get('PIR')}")
    print(f"Audio        : {data.get('AUDIO')}")

    now = time.time()
    for node, seen_time in last_seen.items():
        age = now - seen_time
        if age > NODE_TIMEOUT_SECONDS:
            print(f"WARNING: {node} has not reported for {age:.1f} seconds")