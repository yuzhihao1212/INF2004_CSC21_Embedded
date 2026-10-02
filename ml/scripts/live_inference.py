import re
import joblib
import serial
import pandas as pd


# ============================================================
# SETTINGS
# ============================================================

MODEL_PATH = "ml/models/pico_random_forest_model.pkl"

# CHANGE THIS to your Pico COM port
SERIAL_PORT = "COM5"

BAUD_RATE = 115200


# ============================================================
# FEATURE NAMES
# Must match the model training order exactly
# ============================================================

FEATURE_COLUMNS = [
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
]


# ============================================================
# LOAD MODEL
# ============================================================

model = joblib.load(
    MODEL_PATH
)

print("Model loaded.")
print(
    "Classes:",
    list(model.classes_)
)

print()


# ============================================================
# OPEN SERIAL CONNECTION
# ============================================================

ser = serial.Serial(
    SERIAL_PORT,
    BAUD_RATE,
    timeout=1
)

print(
    f"Listening to Pico on {SERIAL_PORT}..."
)

print(
    "Make sounds near the microphone."
)

print()


# ============================================================
# PARSE FEATURE VECTOR
# ============================================================

def parse_feature_vector(line):

    match = re.search(
        r"FEATURE_VECTOR=\[(.*?)\]",
        line
    )

    if not match:
        return None

    values_text = match.group(1)

    try:
        values = [
            float(value.strip())
            for value in values_text.split(",")
        ]

    except ValueError:
        return None

    if len(values) != 20:

        print(
            f"Invalid feature count: {len(values)}"
        )

        return None

    return values


# ============================================================
# LIVE LOOP
# ============================================================

try:

    while True:

        line = ser.readline().decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if not line:
            continue

        features = parse_feature_vector(
            line
        )

        if features is None:
            continue

        # Convert to DataFrame using the exact
        # feature names used during training
        X = pd.DataFrame(
            [features],
            columns=FEATURE_COLUMNS
        )

        prediction = model.predict(
            X
        )[0]

        probabilities = model.predict_proba(
            X
        )[0]

        confidence = probabilities.max()

        print(
            f"Prediction: {prediction:<22} "
            f"Confidence: {confidence:.2f}"
        )


# ============================================================
# CTRL+C
# ============================================================

except KeyboardInterrupt:

    print()
    print("Live inference stopped.")


finally:

    ser.close()