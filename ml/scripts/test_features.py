import joblib
import pandas as pd


# ============================================================
# SETTINGS
# ============================================================

MODEL_PATH = "ml/models/random_forest_model.pkl"

EXCEL_PATH = "mosaic_quiet_lecture_dataset.xlsx"


# Moe's 20 feature column names in the Excel file
FEATURE_NAMES = [
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


# Current model ignores:
# feature_0  = mean RMS
# feature_10 = std RMS

FEATURE_COLUMNS = [
    "feature_1",
    "feature_2",
    "feature_3",
    "feature_4",
    "feature_5",
    "feature_6",
    "feature_7",
    "feature_8",
    "feature_9",

    "feature_11",
    "feature_12",
    "feature_13",
    "feature_14",
    "feature_15",
    "feature_16",
    "feature_17",
    "feature_18",
    "feature_19",
]


# ============================================================
# LOAD MODEL
# ============================================================

model = joblib.load(
    MODEL_PATH
)

print("Model loaded.")
print()

print(
    "Model expects:",
    model.n_features_in_,
    "features"
)

print()


# ============================================================
# TEST ONE SHEET
# ============================================================

def test_sheet(
    sheet_name,
    expected_class
):

    # Moe's actual column headers begin on row 4
    df = pd.read_excel(
        EXCEL_PATH,
        sheet_name=sheet_name,
        header=3
    )

    # Remove empty rows
    df = df.dropna(
        how="all"
    )

    # Keep only rows with sample IDs
    df = df[
        df["sample_id"].notna()
    ].copy()

    print("=" * 60)

    print(
        f"Testing sheet: {sheet_name}"
    )

    print(
        f"Expected class: {expected_class}"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # Extract all 20 values from Moe's Excel file
    # --------------------------------------------------------

    X = df[
        FEATURE_NAMES
    ].copy()

    # Rename columns to same names used during training
    X.columns = [
        f"feature_{i}"
        for i in range(20)
    ]

    # --------------------------------------------------------
    # Remove RMS features
    # Current model uses 18 features
    # --------------------------------------------------------

    X = X[
        FEATURE_COLUMNS
    ]

    print(
        "Features sent to model:",
        X.shape[1]
    )

    print()

    # --------------------------------------------------------
    # Predict
    # --------------------------------------------------------

    predictions = model.predict(
        X
    )

    probabilities = model.predict_proba(
        X
    )

    df["prediction"] = predictions

    df["confidence"] = (
        probabilities.max(
            axis=1
        )
    )

    # --------------------------------------------------------
    # Show each prediction
    # --------------------------------------------------------

    for _, row in df.iterrows():

        print(
            f"Sample {row['sample_id']} "
            f"→ {row['prediction']} "
            f"(confidence: "
            f"{row['confidence']:.2f})"
        )

    # --------------------------------------------------------
    # Accuracy
    # --------------------------------------------------------

    correct = (
        df["prediction"]
        == expected_class
    ).sum()

    total = len(
        df
    )

    accuracy = (
        correct
        / total
    )

    print()

    print(
        f"Correct: "
        f"{correct}/{total}"
    )

    print(
        f"Accuracy: "
        f"{accuracy * 100:.2f}%"
    )

    print()

    print(
        "Prediction counts:"
    )

    print(
        df["prediction"]
        .value_counts()
    )

    print()

    return df


# ============================================================
# MAIN
# ============================================================

def main():

    quiet_results = test_sheet(
        "Quiet",
        "background_noise"
    )

    lecture_results = test_sheet(
        "Lecture",
        "lecturer_speech"
    )

    # --------------------------------------------------------
    # Overall results
    # --------------------------------------------------------

    quiet_correct = (
        quiet_results[
            "prediction"
        ]
        == "background_noise"
    ).sum()

    lecture_correct = (
        lecture_results[
            "prediction"
        ]
        == "lecturer_speech"
    ).sum()

    total_correct = (
        quiet_correct
        + lecture_correct
    )

    total_samples = (
        len(
            quiet_results
        )
        + len(
            lecture_results
        )
    )

    overall_accuracy = (
        total_correct
        / total_samples
    )

    print("=" * 60)
    print(
        "OVERALL PICO FEATURE VALIDATION"
    )
    print("=" * 60)

    print(
        f"Quiet correct: "
        f"{quiet_correct}/"
        f"{len(quiet_results)}"
    )

    print(
        f"Lecture correct: "
        f"{lecture_correct}/"
        f"{len(lecture_results)}"
    )

    print()

    print(
        f"Total correct: "
        f"{total_correct}/"
        f"{total_samples}"
    )

    print(
        f"Overall accuracy: "
        f"{overall_accuracy * 100:.2f}%"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()