import os
import joblib
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    classification_report
)


# ============================================================
# SETTINGS
# ============================================================

DATASET = "ml/data/pico_combined_dataset.csv"

MODEL_DIR = "ml/models"

MODEL_PATH = os.path.join(
    MODEL_DIR,
    "pico_random_forest_model.pkl"
)


# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(DATASET)

print("Dataset loaded.")
print()

print("Samples per class:")
print(df["label"].value_counts())

print()


# ============================================================
# SELECT 20 PICO FEATURES
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


X = df[FEATURE_COLUMNS]

y = df["label"]


# ============================================================
# TRAIN / TEST SPLIT
# ============================================================

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)


# ============================================================
# TRAIN MODEL
# ============================================================

model = RandomForestClassifier(
    n_estimators=200,
    class_weight="balanced",
    random_state=42
)

model.fit(
    X_train,
    y_train
)


# ============================================================
# TEST MODEL
# ============================================================

predictions = model.predict(
    X_test
)

accuracy = accuracy_score(
    y_test,
    predictions
)


print("Training samples:", len(X_train))
print("Testing samples:", len(X_test))

print()

print("Accuracy:")
print(f"{accuracy:.4f}")

print()

CLASS_NAMES = [
    "background_noise",
    "lecturer_speech",
    "student_conversation",
    "transient_noise",
]


print("Confusion Matrix:")

print(
    confusion_matrix(
        y_test,
        predictions,
        labels=CLASS_NAMES
    )
)

print()

print("Classification Report:")

print(
    classification_report(
        y_test,
        predictions
    )
)


# ============================================================
# SAVE MODEL
# ============================================================

os.makedirs(
    MODEL_DIR,
    exist_ok=True
)

joblib.dump(
    model,
    MODEL_PATH
)

print()
print("Model saved to:")
print(MODEL_PATH)