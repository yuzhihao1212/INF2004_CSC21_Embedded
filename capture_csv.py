import serial
import csv

PORT = "COM4"
BAUD = 115200
# OUTPUT_FILE = "background.csv"
#OUTPUT_FILE = "lecture.csv"
OUTPUT_FILE = "transient.csv"
#OUTPUT_FILE = "talking.csv"
# OUTPUT_FILE = "background.csv"

header = [
    "sample_id",
    "label",
    "mean_rms",
    "mean_centroid",
    "mean_low_ratio",
    "mean_mid_ratio",
    "mean_high_ratio",
    "mean_mfcc1",
    "mean_mfcc2",
    "mean_mfcc3",
    "mean_mfcc4",
    "mean_mfcc5",
    "std_rms",
    "std_centroid",
    "std_low_ratio",
    "std_mid_ratio",
    "std_high_ratio",
    "std_mfcc1",
    "std_mfcc2",
    "std_mfcc3",
    "std_mfcc4",
    "std_mfcc5"
]

ser = serial.Serial(PORT, BAUD, timeout=1)

with open(OUTPUT_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)

    print("Capturing data. Press Ctrl+C to stop.")

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            print(line)

            # save only the CSV-style data rows
            if line[0].isdigit():
                row = line.split(",")

                if len(row) == 22:
                    writer.writerow(row)
                    f.flush()

    except KeyboardInterrupt:
        pass

ser.close()

print("Saved to", OUTPUT_FILE)