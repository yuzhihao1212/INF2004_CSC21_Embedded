import csv
import serial

PORT = "COM5"  # change if Pico W appears on a different COM port
BAUD = 115200
LABEL = "transient"  # background, lecture, talking, or transient
OUTPUT_FILE = f"{LABEL}.csv"

header = [
    "sample_id", "label",
    "mean_rms", "mean_centroid", "mean_low_ratio", "mean_mid_ratio", "mean_high_ratio",
    "mean_mfcc1", "mean_mfcc2", "mean_mfcc3", "mean_mfcc4", "mean_mfcc5",
    "std_rms", "std_centroid", "std_low_ratio", "std_mid_ratio", "std_high_ratio",
    "std_mfcc1", "std_mfcc2", "std_mfcc3", "std_mfcc4", "std_mfcc5",
]

sample_id = 0
with serial.Serial(PORT, BAUD, timeout=1) as ser, open(OUTPUT_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    print(f"Capturing {LABEL} features from {PORT}. Press Ctrl+C to stop.")
    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if not line.startswith("FEATURES_Q8="):
                continue
            raw_values = line.split("=", 1)[1].split(",")
            if len(raw_values) != 20:
                print("Skipping incomplete feature vector:", line)
                continue
            try:
                features = [int(value.strip()) for value in raw_values]
            except ValueError:
                print("Skipping invalid feature vector:", line)
                continue
            sample_id += 1
            writer.writerow([sample_id, LABEL, *features])
            f.flush()
            print(f"Saved sample {sample_id}: {features}")
    except KeyboardInterrupt:
        pass

print(f"Saved {sample_id} samples to {OUTPUT_FILE}")
