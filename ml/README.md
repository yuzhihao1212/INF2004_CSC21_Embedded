# Audio model training and data

This directory contains the PC-side development tools for preparing audio
datasets, and the training scripts for the earlier random-forest classifier.

The Pico W now runs a different model: the int8 network in
[S2](../node/app_program/subsystem2/dsp_int8_candidate.c), fed by S1's
fixed-point features. Its weights are in that file. Its source record,
[SOURCE.json](../firmware/audio/classifier/SOURCE.json), names
`ml/candidates/dsp_int8_cough_tuned/model.json` and gives its SHA-256, but that
folder and the script that trained and quantised the network are not in this
repository. The scripts below do not reproduce the deployed model.

| File | Purpose |
| --- | --- |
| [build_dataset.py](scripts/build_dataset.py) | Prepare the feature dataset |
| [train_pico_model.py](scripts/train_pico_model.py) | Train the earlier random-forest model from `ml/data/pico_combined_dataset.csv` |
| [extract_features.py](scripts/extract_features.py) | Audio feature extraction for offline work |
| [test_features.py](scripts/test_features.py) | Offline feature checks |
| [data/](data/) | Retained feature datasets for reproducibility |

For offline development, create a Python virtual environment at the repository
root and install [requirements.txt](../requirements.txt). Run the training scripts
from the repository root so their existing relative paths resolve correctly.

Keep the raw audio and large generated models out of Git. The final node and
dashboard can run using the existing model and firmware without retraining.
