"""Capture versioned per-frame log-mel packets from audio_sequence_capture.uf2.

Example from repository root:
  .venv/Scripts/python.exe ml/scripts/capture_audio_sequences.py \
      --label lecture --source-id lecture_video06 --output ml/data/sequences/lecture_video06.jsonl
Outputs use exclusive creation; previous recordings cannot be overwritten.
"""
import argparse
import json
from pathlib import Path
import time


class SequenceParser:
    """Accept complete ordered packets only; a malformed packet is discarded."""
    def __init__(self):
        self.packet = None
        self.discarded = 0

    def feed(self, line):
        fields = line.strip().split(",")
        kind = fields[0]
        if kind not in {"SEQ_BEGIN", "SEQ_FRAME", "SEQ_SUMMARY", "SEQ_END"}:
            return None
        try:
            values = [int(v) for v in fields[1:]]
            if kind == "SEQ_BEGIN":
                if self.packet is not None:
                    self.discarded += 1
                self.packet = None
                if len(values) != 11 or values[0] != 1 or values[3:5] != [48,20]:
                    raise ValueError("Unsupported sequence header")
                version, window, delivered, frames, bands, minimum, maximum, mean, rms, rails, dsp = (
                    values[0], values[1], values[2], values[3], values[4], values[5],
                    values[6], values[7], values[8], values[9], values[10])
                if not (0 <= window < 2**32 and delivered >= 0 and 0 <= minimum <= maximum <= 4095
                        and 0 <= mean <= 4095*256 and rms >= 0 and 0 <= rails <= 8000 and dsp >= 0):
                    raise ValueError("Invalid header values")
                self.packet = dict(protocol_version=version, frontend="mosaic_fixed_mel20_q8_v1",
                    window_id=window, delivered_us=delivered,
                    sample_rate=16000, window_samples=8000, frame_samples=400, hop_samples=160,
                    mel_bands=bands, adc_min=minimum, adc_max=maximum, adc_mean_q8=mean,
                    adc_ac_rms_q8=rms, adc_near_rail_samples=rails, dsp_us=dsp,
                    mel_log_q8=[], frame_rms_q8=[])
                return None
            packet = self.packet
            if packet is None:
                return None
            if not values or values[0] != packet["window_id"]:
                raise ValueError("Window ID mismatch")
            if kind == "SEQ_FRAME":
                if len(values) != 23 or values[1] != len(packet["mel_log_q8"]):
                    raise ValueError("Missing, duplicate or unordered frame")
                if len(packet["mel_log_q8"]) >= 48 or not 0 <= values[2] < 2**31:
                    raise ValueError("Invalid frame RMS")
                if any(not -32768 <= v <= 32767 for v in values[3:]):
                    raise ValueError("Invalid mel Q8")
                packet["frame_rms_q8"].append(values[2])
                packet["mel_log_q8"].append(values[3:])
            elif kind == "SEQ_SUMMARY":
                if len(values) != 21 or "summary_q8" in packet or len(packet["mel_log_q8"]) != 48:
                    raise ValueError("Invalid summary")
                if any(not -(2**31) <= v < 2**31 for v in values[1:]):
                    raise ValueError("Summary overflow")
                packet["summary_q8"] = values[1:]
            else:
                if len(values) != 1 or len(packet["mel_log_q8"]) != 48 or "summary_q8" not in packet:
                    raise ValueError("Incomplete sequence")
                self.packet = None
                return packet
        except ValueError:
            self.packet = None
            self.discarded += 1
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--label", required=True, choices=["lecture", "talking"])
    parser.add_argument("--source-id", required=True, help="Same video must always use the same source ID")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.source_id.strip():
        parser.error("--source-id must identify the source video")
    if args.output.suffix.lower() != ".jsonl":
        parser.error("--output must end in .jsonl for sequence training")
    import serial
    args.output.parent.mkdir(parents=True, exist_ok=True)
    decoder, count, last_us = SequenceParser(), 0, None
    started, warned = time.monotonic(), False
    try:
        with serial.Serial(args.port, args.baud, timeout=0.25) as ser, args.output.open("x", encoding="utf-8") as target:
            print(f"Capturing {args.label}, source {args.source_id}, to {args.output}. Ctrl+C stops.")
            while True:
                line = ser.readline(4096).decode("ascii", errors="replace")
                packet = decoder.feed(line) if line else None
                if packet is not None:
                    packet.update(record_type="window", label=args.label, source_id=args.source_id)
                    gap = packet["delivered_us"]-last_us if last_us is not None else None
                    packet["delivery_gap_us"] = gap
                    packet["possible_delivery_gap"] = gap is not None and (gap < 250000 or gap > 750000)
                    if packet["possible_delivery_gap"]:
                        print("Delivery timing discontinuity; preserve this boundary during training.")
                    last_us = packet["delivered_us"]
                    target.write(json.dumps(packet, separators=(",", ":"))+"\n")
                    target.flush()
                    count += 1
                    print(f"Saved window {packet['window_id']}: 48 x 20 mel frames; "
                          f"near-rail samples {packet['adc_near_rail_samples']}/8000")
                if not count and not warned and time.monotonic()-started > 10:
                    print("No complete sequence packets yet. This script requires audio_sequence_capture.uf2.")
                    warned = True
    except KeyboardInterrupt:
        pass
    except (serial.SerialException, OSError) as error:
        raise SystemExit(f"Capture stopped: {error}") from error
    print(f"Saved {count} windows. Discarded incomplete/invalid packets: {decoder.discarded}.")


if __name__ == "__main__":
    main()
