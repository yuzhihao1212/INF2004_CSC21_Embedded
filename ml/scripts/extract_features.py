import numpy as np
import librosa

SAMPLE_RATE = 16000
N_FFT = 512
HOP_LENGTH = 160
WIN_LENGTH = 400
N_MFCC = 5


def extract_features(audio):

    # --------------------------------------------------------
    # RMS
    # --------------------------------------------------------
    rms = librosa.feature.rms(
        y=audio,
        frame_length=WIN_LENGTH,
        hop_length=HOP_LENGTH
    )[0]

    # --------------------------------------------------------
    # Spectral centroid
    # --------------------------------------------------------
    spectral_centroid = librosa.feature.spectral_centroid(
        y=audio,
        sr=SAMPLE_RATE,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        win_length=WIN_LENGTH,
        window="hamming"
    )[0]

    # --------------------------------------------------------
    # STFT
    # --------------------------------------------------------
    stft = np.abs(
        librosa.stft(
            audio,
            n_fft=N_FFT,
            hop_length=HOP_LENGTH,
            win_length=WIN_LENGTH,
            window="hamming"
        )
    )

    power = stft ** 2

    freqs = librosa.fft_frequencies(
        sr=SAMPLE_RATE,
        n_fft=N_FFT
    )

    total_energy = np.sum(
        power,
        axis=0
    ) + 1e-10

    # --------------------------------------------------------
    # Frequency-band ratios
    # --------------------------------------------------------
    def band_ratio(low, high):

        mask = (
            (freqs >= low) &
            (freqs < high)
        )

        band_energy = np.sum(
            power[mask],
            axis=0
        )

        return (
            band_energy /
            total_energy
        )

    low_ratio = band_ratio(
        125,
        500
    )

    mid_ratio = band_ratio(
        500,
        2000
    )

    high_ratio = band_ratio(
        2000,
        7500
    )

    # --------------------------------------------------------
    # MFCC
    # --------------------------------------------------------
    mfcc = librosa.feature.mfcc(
        y=audio,
        sr=SAMPLE_RATE,
        n_mfcc=N_MFCC,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        win_length=WIN_LENGTH,
        window="hamming"
    )

    # --------------------------------------------------------
    # Combine 10 frame-level features
    # --------------------------------------------------------
    frame_features = np.vstack([
        rms,
        spectral_centroid,
        low_ratio,
        mid_ratio,
        high_ratio,
        mfcc
    ])

    # Mean of each feature
    means = np.mean(
        frame_features,
        axis=1
    )

    # Standard deviation of each feature
    stds = np.std(
        frame_features,
        axis=1
    )

    # 10 means + 10 std = 20 features
    feature_vector = np.concatenate([
        means,
        stds
    ])

    return feature_vector


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    test_file = (
        "ml/data/lecturer_speech/"
        "lecturer_000.wav"
    )

    audio, _ = librosa.load(
        test_file,
        sr=SAMPLE_RATE,
        mono=True,
        duration=0.5
    )

    features = extract_features(
        audio
    )

    print(
        "Number of features:",
        len(features)
    )

    print(features)