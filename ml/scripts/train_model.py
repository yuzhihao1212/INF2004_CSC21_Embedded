import os
import joblib
import pandas as pd

from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    classification_report
)


# ============================================================
# SETTINGS
# ============================================================

DATASET = "ml/features/dataset.csv"

MODEL_DIR = "ml/models"

MODEL_PATH = os.path.join(
    MODEL_DIR,
    "random_forest_model.pkl"
)


# ============================================================
# LOAD DATASET
# ============================================================

df = pd.read_csv(
    DATASET
)


# ============================================================
# SELECT FEATURES
#
# Ignore:
# feature_0  = mean RMS
# feature_10 = std RMS
#
# These depend heavily on microphone / ADC amplitude.
# ============================================================

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


X = df[
    FEATURE_COLUMNS
]

y = df[
    "label"
]

groups = df[
    "source_file"
]


# ============================================================
# GROUP-BASED TRAIN / TEST SPLIT
#
# Windows from the same original WAV file
# stay entirely in train OR test.
# ============================================================

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.2,
    random_state=42
)

train_index, test_index = next(
    splitter.split(
        X,
        y,
        groups=groups
    )
)


X_train = X.iloc[
    train_index
]

X_test = X.iloc[
    test_index
]

y_train = y.iloc[
    train_index
]

y_test = y.iloc[
    test_index
]


# ============================================================
# TRAIN RANDOM FOREST
# ============================================================

model = RandomForestClassifier(
    n_estimators=100,
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


print()
print(
    "Features used:",
    len(FEATURE_COLUMNS)
)

print(
    "Ignored features:",
    "feature_0 and feature_10"
)

print()

print(
    "Training windows:",
    len(X_train)
)

print(
    "Testing windows:",
    len(X_test)
)


print()
print(
    "Training class distribution:"
)

print(
    y_train.value_counts()
)


print()
print(
    "Testing class distribution:"
)

print(
    y_test.value_counts()
)


print()
print("Accuracy:")

print(
    f"{accuracy:.4f}"
)


# ============================================================
# CONFUSION MATRIX
# ============================================================

CLASS_NAMES = [
    "lecturer_speech",
    "student_conversation",
    "background_noise",
    "transient_noise",
]


print()
print(
    "Confusion Matrix:"
)

print(
    confusion_matrix(
        y_test,
        predictions,
        labels=CLASS_NAMES
    )
)


# ============================================================
# CLASSIFICATION REPORT
# ============================================================

print()
print(
    "Classification Report:"
)

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
print(
    "Model saved to:"
)

print(
    MODEL_PATH
)