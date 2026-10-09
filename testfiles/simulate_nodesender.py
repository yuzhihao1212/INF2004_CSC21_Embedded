import socket
import time
import random

PC_IP = "127.0.0.1"
PC_PORT = 5005

NODE_ID = "node-01"
ZONE_ID = "front-left"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    temp = round(random.uniform(24.0, 27.0), 1)
    hum = round(random.uniform(55.0, 70.0), 1)
    co2 = random.randint(500, 900)
    pir = random.choice([0, 1])
    audio = random.choice(["QUIET", "LECTURE", "DISCUSSION", "CHATTER"])

    message = (
        f"NODE={NODE_ID},"
        f"ZONE={ZONE_ID},"
        f"TEMP={temp},"
        f"HUM={hum},"
        f"CO2={co2},"
        f"PIR={pir},"
        f"AUDIO={audio}"
    )

    sock.sendto(message.encode("utf-8"), (PC_IP, PC_PORT))

    print(f"Sent: {message}")
    time.sleep(2)