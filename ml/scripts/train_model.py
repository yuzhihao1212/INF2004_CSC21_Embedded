import os
import pandas as pd

from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    classification_report
)
import joblib


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
# LOAD DATA
# ============================================================

df = pd.read_csv(DATASET)

feature_columns = [
    column
    for column in df.columns
    if column.startswith("feature_")
]

X = df[feature_columns]
y = df["label"]

# Important:
# all 500 ms windows from the same WAV stay together
groups = df["source_file"]


# ============================================================
# GROUP-BASED TRAIN / TEST SPLIT
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

X_train = X.iloc[train_index]
X_test = X.iloc[test_index]

y_train = y.iloc[train_index]
y_test = y.iloc[test_index]


# ============================================================
# TRAIN MODEL
# ============================================================

model = RandomForestClassifier(
    n_estimators=100,
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
print("Training windows:", len(X_train))
print("Testing windows:", len(X_test))

print()
print("Training class distribution:")
print(y_train.value_counts())

print()
print("Testing class distribution:")
print(y_test.value_counts())

print()
print("Accuracy:")
print(f"{accuracy:.4f}")

print()
print("Confusion Matrix:")
print(
    confusion_matrix(
        y_test,
        predictions,
        labels=[
            "lecturer_speech",
            "student_conversation",
            "background_noise",
            "transient_noise"
        ]
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