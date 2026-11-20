#!/usr/bin/env python3
"""Show the node telemetry arriving at the existing MQTT broker.

Run from pc/: python3 tools/live_node_stream.py [--csv /path/to/log.csv]
This is a separate subscriber; it does not change dashboard or node settings.
"""
import argparse
import csv
from datetime import datetime
from pathlib import Path
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mosaic import protocol as p
from mosaic.mqtt import MqttClient, MqttError

FIELDS = ("time", "node", "packet_seq", "window_seq", "class", "background_pct",
          "speech_pct", "reserved_pct", "transient_pct", "filtered_rms_adc",
          "temperature_c", "humidity_pct", "co2_ppm", "co2_warmup", "motion_pct",
          "rssi_dbm", "dsp_ms", "inference_ms", "audio_overruns", "config_version")


def rows(header, packet):
    flags = packet.valid_flags
    count = len(packet.audio)
    values = dict(time=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                  node=header.node_id, packet_seq=header.seq,
                  temperature_c=packet.temperature_c if p.Valid.TEMP_HUM in flags else None,
                  humidity_pct=packet.humidity_pct if p.Valid.TEMP_HUM in flags else None,
                  co2_ppm=packet.co2_ppm if p.Valid.CO2 in flags else None,
                  co2_warmup=p.Valid.CO2_WARMUP in flags,
                  motion_pct=packet.pir_active_pct if p.Valid.PIR in flags else None,
                  rssi_dbm=packet.wifi_rssi_dbm, dsp_ms=round(packet.dsp_time_us / 1000, 3),
                  inference_ms=round(packet.inference_time_us / 1000, 3),
                  audio_overruns=packet.audio_overruns, config_version=packet.config_version)
    if not count:
        yield dict(values, window_seq=None, **{"class": "NO_AUDIO"})
    for index, window in enumerate(packet.audio):
        seq = (packet.audio_window_seq - count + 1 + index) & 0xffff
        yield dict(values, window_seq=seq, **{"class": window.audio_class.name},
                   background_pct=window.prob_pct[0], speech_pct=window.prob_pct[1],
                   reserved_pct=window.prob_pct[2], transient_pct=window.prob_pct[3],
                   filtered_rms_adc=window.rms)


def display(row):
    def show(value, suffix=""):
        return "--" if value is None else f"{value}{suffix}"
    print(f"{row['time'][11:23]}  node {row['node']} pkt {row['packet_seq']} "
          f"win {show(row['window_seq'])}  {row['class']}  "
          f"P(bg/speech/transient)={show(row.get('background_pct'))}/"
          f"{show(row.get('speech_pct'))}/{show(row.get('transient_pct'))}%  "
          f"filtered RMS={show(row.get('filtered_rms_adc'))} ADC  "
          f"temp={show(row['temperature_c'], 'C')} RH={show(row['humidity_pct'], '%')} "
          f"CO2={show(row['co2_ppm'], 'ppm')} motion={show(row['motion_pct'], '%')}  "
          f"RSSI={row['rssi_dbm']}dBm DSP={row['dsp_ms']}ms ML={row['inference_ms']}ms "
          f"overruns={row['audio_overruns']} config={row['config_version']}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--broker', default='127.0.0.1', help='MQTT broker address')
    ap.add_argument('--port', type=int, default=1883)
    ap.add_argument('--csv', type=Path, help='Save the same observations to a CSV file')
    args = ap.parse_args()
    client = MqttClient(args.broker, args.port, client_id=f'mosaic-live-{time.time_ns()}')
    file = None
    try:
        if args.csv:
            file = args.csv.open('x', newline='', encoding='utf-8')
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            file.flush()
        else:
            writer = None
        client.connect()
        client.subscribe('mosaic/node/+/telemetry')
        print('Listening for both nodes. Probabilities are per 500 ms window; '
              'RMS is filtered ADC counts, not sound level or raw waveform. Ctrl+C to stop.', flush=True)
        while True:
            if select.select([client.fileno()], [], [], 1)[0]:
                for message in client.read():
                    try:
                        header, packet = p.decode(message.payload)
                        if header.msg_type != p.MsgType.TELEMETRY:
                            continue
                        for row in rows(header, packet):
                            display(row)
                            if writer:
                                writer.writerow(row)
                                file.flush()
                    except (p.ProtocolError, ValueError) as exc:
                        print(f'Invalid telemetry on {message.topic}: {exc}', file=sys.stderr, flush=True)
            client.tick()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (OSError, MqttError, ConnectionError) as exc:
        print(f'Live stream stopped: {exc}', file=sys.stderr)
        return 1
    finally:
        client.close()
        if file:
            file.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
