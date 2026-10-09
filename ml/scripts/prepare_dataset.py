import os
import csv
import tarfile
import zipfile
import urllib.request
import random

import librosa
import soundfile as sf


# ============================================================
# SETTINGS
# ============================================================

TARGET_SR = 16000
SAMPLES_PER_CLASS = 300

BASE_DIR = "ml"
RAW_DIR = os.path.join(BASE_DIR, "raw_datasets")
DATA_DIR = os.path.join(BASE_DIR, "data")

LECTURER_DIR = os.path.join(DATA_DIR, "lecturer_speech")
CONVERSATION_DIR = os.path.join(DATA_DIR, "student_conversation")
BACKGROUND_DIR = os.path.join(DATA_DIR, "background_noise")
TRANSIENT_DIR = os.path.join(DATA_DIR, "transient_noise")

LIBRISPEECH_URL = (
    "https://www.openslr.org/resources/31/train-clean-5.tar.gz"
)

ESC50_URL = (
    "https://github.com/karolpiczak/ESC-50/archive/refs/heads/master.zip"
)

AMI_URLS = [
    "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/IS1001a/audio/IS1001a.Mix-Headset.wav",
    "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/IS1008d/audio/IS1008d.Mix-Headset.wav",
    "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/IS1006b/audio/IS1006b.Mix-Headset.wav",
]

random.seed(42)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def make_directories():
    folders = [
        RAW_DIR,
        LECTURER_DIR,
        CONVERSATION_DIR,
        BACKGROUND_DIR,
        TRANSIENT_DIR,
    ]

    for folder in folders:
        os.makedirs(folder, exist_ok=True)


def download_file(url, destination):
    if os.path.exists(destination):
        print(f"Already downloaded: {destination}")
        return

    print(f"Downloading:\n{url}")
    urllib.request.urlretrieve(url, destination)
    print("Download complete.")


def convert_to_wav(source, destination):
    audio, _ = librosa.load(
        source,
        sr=TARGET_SR,
        mono=True
    )

    sf.write(
        destination,
        audio,
        TARGET_SR,
        subtype="PCM_16"
    )


# ============================================================
# LIBRISPEECH → LECTURER SPEECH
# ============================================================

def prepare_librispeech():
    archive = os.path.join(
        RAW_DIR,
        "train-clean-5.tar.gz"
    )

    extracted = os.path.join(
        RAW_DIR,
        "LibriSpeech"
    )

    download_file(
        LIBRISPEECH_URL,
        archive
    )

    if not os.path.exists(extracted):
        print("Extracting Mini LibriSpeech...")

        with tarfile.open(
            archive,
            "r:gz"
        ) as tar:
            tar.extractall(RAW_DIR)

    flac_files = []

    for root, _, files in os.walk(extracted):
        for filename in files:
            if filename.endswith(".flac"):
                flac_files.append(
                    os.path.join(root, filename)
                )

    random.shuffle(flac_files)

    selected = flac_files[:SAMPLES_PER_CLASS]

    print(
        f"Preparing {len(selected)} lecturer speech clips..."
    )

    for i, source in enumerate(selected):
        destination = os.path.join(
            LECTURER_DIR,
            f"lecturer_{i:03d}.wav"
        )

        convert_to_wav(
            source,
            destination
        )


# ============================================================
# ESC-50
# ============================================================

def prepare_esc50():
    archive = os.path.join(
        RAW_DIR,
        "esc50.zip"
    )

    extracted = os.path.join(
        RAW_DIR,
        "ESC-50-master"
    )

    download_file(
        ESC50_URL,
        archive
    )

    if not os.path.exists(extracted):
        print("Extracting ESC-50...")

        with zipfile.ZipFile(
            archive,
            "r"
        ) as zip_ref:
            zip_ref.extractall(RAW_DIR)

    metadata_file = os.path.join(
        extracted,
        "meta",
        "esc50.csv"
    )

    audio_dir = os.path.join(
        extracted,
        "audio"
    )

    transient_categories = {
    "coughing",
    "door_wood_knock",
    "clapping",
    "sneezing",
    "footsteps",
    "mouse_click",
    "glass_breaking",
    "can_opening",
    "door_wood_creaks",
}

    background_categories = {
        "clock_tick",
        "vacuum_cleaner",
        "washing_machine",
    }

    transient_files = []
    background_files = []

    with open(
        metadata_file,
        newline="",
        encoding="utf-8"
    ) as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            category = row["category"]

            source = os.path.join(
                audio_dir,
                row["filename"]
            )

            if category in transient_categories:
                transient_files.append(source)

            if category in background_categories:
                background_files.append(source)

    random.shuffle(transient_files)
    random.shuffle(background_files)

    transient_files = transient_files[:SAMPLES_PER_CLASS]
    background_files = background_files[:SAMPLES_PER_CLASS]

    print(
        f"Preparing {len(transient_files)} transient clips..."
    )

    for i, source in enumerate(transient_files):
        destination = os.path.join(
            TRANSIENT_DIR,
            f"transient_{i:03d}.wav"
        )

        convert_to_wav(
            source,
            destination
        )

    print(
        f"Preparing {len(background_files)} background clips..."
    )

    for i, source in enumerate(background_files):
        destination = os.path.join(
            BACKGROUND_DIR,
            f"background_{i:03d}.wav"
        )

        convert_to_wav(
            source,
            destination
        )


# ============================================================
# AMI → STUDENT CONVERSATION
# ============================================================

def prepare_ami():
    ami_folder = os.path.join(
        RAW_DIR,
        "ami"
    )

    os.makedirs(
        ami_folder,
        exist_ok=True
    )

    for url in AMI_URLS:
        filename = url.split("/")[-1]

        destination = os.path.join(
            ami_folder,
            filename
        )

        download_file(
            url,
            destination
        )

    wav_files = []

    for root, _, files in os.walk(ami_folder):
        for filename in files:
            if filename.lower().endswith(".wav"):
                wav_files.append(
                    os.path.join(root, filename)
                )

    random.shuffle(wav_files)

    count = 0
    clip_length = TARGET_SR * 5

    for source in wav_files:
        audio, _ = librosa.load(
            source,
            sr=TARGET_SR,
            mono=True
        )

        for start in range(
            0,
            len(audio) - clip_length,
            clip_length
        ):
            clip = audio[
                start:start + clip_length
            ]

            # Skip nearly silent segments
            if max(abs(clip)) < 0.01:
                continue

            destination = os.path.join(
                CONVERSATION_DIR,
                f"conversation_{count:03d}.wav"
            )

            sf.write(
                destination,
                clip,
                TARGET_SR,
                subtype="PCM_16"
            )

            count += 1

            if count >= SAMPLES_PER_CLASS:
                print(
                    f"Prepared {count} conversation clips."
                )
                return


# ============================================================
# MAIN
# ============================================================

def main():
    print("Preparing MOSAIC dataset...")
    print()

    make_directories()

    prepare_librispeech()
    prepare_esc50()
    prepare_ami()

    print()
    print("Dataset preparation finished.")
    print()
    print("Expected folders:")
    print(LECTURER_DIR)
    print(CONVERSATION_DIR)
    print(BACKGROUND_DIR)
    print(TRANSIENT_DIR)


if __name__ == "__main__":
    main()