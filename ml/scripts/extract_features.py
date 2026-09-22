import os
import numpy as np
import librosa

SAMPLE_RATE = 16000
N_FFT = 512
HOP_LENGTH = 160
WIN_LENGTH = 400
N_MFCC = 5

def extract_features(file_path):
    y, sr = librosa.load(file_path, sr=SAMPLE_RATE, mono=True)

    rms = librosa.feature.rms(
        y=y,
        frame_length=WIN_LENGTH,
        hop_length=HOP_LENGTH
    )[0]

    spectral_centroid = librosa.feature.spectral_centroid(
        y=y,
        sr=sr,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        win_length=WIN_LENGTH,
        window="hamming"
    )[0]

    stft = np.abs(
        librosa.stft(
            y,
            n_fft=N_FFT,
            hop_length=HOP_LENGTH,
            win_length=WIN_LENGTH,
            window="hamming"
        )
    )

    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    power = stft ** 2

    total_energy = np.sum(power, axis=0) + 1e-10

    def band_ratio(low, high):
        mask = (freqs >= low) & (freqs < high)
        band_energy = np.sum(power[mask], axis=0)
        return band_energy / total_energy

    low_ratio = band_ratio(125, 500)
    mid_ratio = band_ratio(500, 2000)
    high_ratio = band_ratio(2000, 7500)

    mfcc = librosa.feature.mfcc(
        y=y,
        sr=sr,
        n_mfcc=N_MFCC,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        win_length=WIN_LENGTH,
        window="hamming"
    )

    frame_features = np.vstack([
        rms,
        spectral_centroid,
        low_ratio,
        mid_ratio,
        high_ratio,
        mfcc
    ])

    means = np.mean(frame_features, axis=1)
    stds = np.std(frame_features, axis=1)

    feature_vector = np.concatenate([means, stds])

    return feature_vector


if __name__ == "__main__":
    test_file = "ml/data/lecturer_speech/lecturer_01.wav"

    features = extract_features(test_file)

    print("Number of features:", len(features))
    print(features)