import os
import numpy as np
import pandas as pd
import librosa

from extract_features import extract_features


# ============================================================
# SETTINGS
# ============================================================

DATA_DIR = "ml/data"
OUTPUT_CSV = "ml/features/dataset.csv"

TARGET_SR = 16000

WINDOW_SECONDS = 0.5
WINDOW_SAMPLES = int(TARGET_SR * WINDOW_SECONDS)

TRANSIENT_HOP_SECONDS = 0.25
TRANSIENT_HOP_SAMPLES = int(
    TARGET_SR * TRANSIENT_HOP_SECONDS
)

TRANSIENT_WINDOWS_PER_FILE = 3

SILENCE_THRESHOLD = 0.01

# Cap all larger classes at 1200
MAX_SAMPLES_PER_CLASS = 1200


CLASS_FOLDERS = {
    "lecturer_speech": os.path.join(
        DATA_DIR,
        "lecturer_speech"
    ),

    "student_conversation": os.path.join(
        DATA_DIR,
        "student_conversation"
    ),

    "background_noise": os.path.join(
        DATA_DIR,
        "background_noise"
    ),

    "transient_noise": os.path.join(
        DATA_DIR,
        "transient_noise"
    ),
}


# ============================================================
# RMS ENERGY
# ============================================================

def calculate_rms(audio):

    return np.sqrt(
        np.mean(audio ** 2)
    )


# ============================================================
# NORMAL 500 MS WINDOWS
# ============================================================

def extract_normal_windows(audio):

    windows = []

    for start in range(
        0,
        len(audio) - WINDOW_SAMPLES + 1,
        WINDOW_SAMPLES
    ):

        window = audio[
            start:start + WINDOW_SAMPLES
        ]

        if np.max(np.abs(window)) < SILENCE_THRESHOLD:
            continue

        windows.append(window)

    return windows


# ============================================================
# TRANSIENT WINDOWS
# ============================================================

def extract_transient_windows(audio):

    candidates = []

    for start in range(
        0,
        len(audio) - WINDOW_SAMPLES + 1,
        TRANSIENT_HOP_SAMPLES
    ):

        window = audio[
            start:start + WINDOW_SAMPLES
        ]

        if np.max(np.abs(window)) < SILENCE_THRESHOLD:
            continue

        energy = calculate_rms(window)

        candidates.append(
            (energy, window)
        )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    selected = candidates[
        :TRANSIENT_WINDOWS_PER_FILE
    ]

    return [
        window
        for energy, window in selected
    ]


# ============================================================
# PROCESS ONE AUDIO FILE
# ============================================================

def process_audio_file(
    file_path,
    label
):

    audio, _ = librosa.load(
        file_path,
        sr=TARGET_SR,
        mono=True
    )

    if label == "transient_noise":

        windows = extract_transient_windows(
            audio
        )

    else:

        windows = extract_normal_windows(
            audio
        )

    feature_rows = []

    for window in windows:

        features = extract_features(
            window
        )

        feature_rows.append(
            features
        )

    return feature_rows


# ============================================================
# BUILD DATASET
# ============================================================

def main():

    rows = []

    print(
        "Building improved 500 ms feature dataset..."
    )

    print()

    for label, folder in CLASS_FOLDERS.items():

        print(
            f"Processing: {label}"
        )

        files = [
            filename
            for filename in os.listdir(folder)
            if filename.lower().endswith(".wav")
        ]

        for filename in files:

            file_path = os.path.join(
                folder,
                filename
            )

            feature_rows = process_audio_file(
                file_path,
                label
            )

            for features in feature_rows:

                row = {
                    f"feature_{i}": value
                    for i, value in enumerate(
                        features
                    )
                }

                row["label"] = label
                row["source_file"] = filename

                rows.append(row)

    # --------------------------------------------------------
    # Create dataframe
    # --------------------------------------------------------

    df = pd.DataFrame(rows)

    print()
    print("Before class limit:")
    print(
        df["label"].value_counts()
    )

    # --------------------------------------------------------
    # LIMIT LARGE CLASSES TO 1200
    # --------------------------------------------------------

    limited_parts = []

    for label in df["label"].unique():

        class_df = df[
            df["label"] == label
        ]

        if len(class_df) > MAX_SAMPLES_PER_CLASS:

            class_df = class_df.sample(
                n=MAX_SAMPLES_PER_CLASS,
                random_state=42
            )

        limited_parts.append(
            class_df
        )

    df = pd.concat(
        limited_parts,
        ignore_index=True
    )

    # Shuffle final dataset
    df = df.sample(
        frac=1,
        random_state=42
    ).reset_index(
        drop=True
    )

    # --------------------------------------------------------
    # Save CSV
    # --------------------------------------------------------

    os.makedirs(
        os.path.dirname(
            OUTPUT_CSV
        ),
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_CSV,
        index=False
    )

    # --------------------------------------------------------
    # Display results
    # --------------------------------------------------------

    print()
    print("Dataset created:")
    print(OUTPUT_CSV)

    print()
    print("Total windows:")
    print(len(df))

    print()
    print("Samples per class:")
    print(
        df["label"].value_counts()
    )

    print()
    print("Number of features:")
    print(
        len([
            column
            for column in df.columns
            if column.startswith(
                "feature_"
            )
        ])
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()