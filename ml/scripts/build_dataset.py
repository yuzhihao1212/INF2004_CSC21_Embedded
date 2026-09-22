import os
import csv

from extract_features import extract_features

DATA_DIR = "ml/data"
OUTPUT_FILE = "ml/features/dataset.csv"

CLASSES = [
    "lecturer_speech",
    "student_conversation",
    "background_noise",
    "transient_noise"
]

headers = [
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
    "std_mfcc5",
    "label"
]

os.makedirs("ml/features", exist_ok=True)

rows = []

for class_name in CLASSES:
    folder = os.path.join(DATA_DIR, class_name)

    for filename in os.listdir(folder):
        if filename.endswith(".wav"):
            path = os.path.join(folder, filename)

            features = extract_features(path)

            rows.append(list(features) + [class_name])

            print("Processed:", filename)

with open(OUTPUT_FILE, "w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(headers)
    writer.writerows(rows)

print("Dataset created:", OUTPUT_FILE)