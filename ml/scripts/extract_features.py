import numpy as np


# ============================================================
# SETTINGS — MATCH MOE'S PICO DSP
# ============================================================

SAMPLE_RATE = 16000

AUDIO_SAMPLES = 8000       # 500 ms
FRAME_SIZE = 400           # 25 ms
HOP_SIZE = 160             # 10 ms
NUM_FRAMES = 48

FFT_SIZE = 512

MIN_FREQ = 125.0
LOW_END = 500.0
MID_END = 2000.0
MAX_FREQ = 7500.0

MEL_FILTERS = 20
MFCC_COUNT = 5

HPF_ALPHA = 0.953
EPSILON = 1e-12


# ============================================================
# HAMMING WINDOW
# ============================================================

HAMMING_WINDOW = (
    0.54
    - 0.46
    * np.cos(
        2.0
        * np.pi
        * np.arange(FRAME_SIZE)
        / (FRAME_SIZE - 1)
    )
)


# ============================================================
# MEL CONVERSION
# ============================================================

def hz_to_mel(hz):

    return (
        2595.0
        * np.log10(
            1.0 + hz / 700.0
        )
    )


def mel_to_hz(mel):

    return (
        700.0
        * (
            10.0 ** (
                mel / 2595.0
            )
            - 1.0
        )
    )


# ============================================================
# MEL FILTER BANK BINS
# ============================================================

def create_mel_bins():

    min_mel = hz_to_mel(
        MIN_FREQ
    )

    max_mel = hz_to_mel(
        MAX_FREQ
    )

    bins = []

    for i in range(
        MEL_FILTERS + 2
    ):

        mel = (
            min_mel
            + (
                (max_mel - min_mel)
                * i
                / (MEL_FILTERS + 1)
            )
        )

        hz = mel_to_hz(
            mel
        )

        bin_index = int(
            np.floor(
                (FFT_SIZE + 1)
                * hz
                / SAMPLE_RATE
            )
        )

        bin_index = max(
            0,
            min(
                bin_index,
                FFT_SIZE // 2
            )
        )

        bins.append(
            bin_index
        )

    return np.array(
        bins,
        dtype=int
    )


MEL_BINS = create_mel_bins()


# ============================================================
# PREPROCESS AUDIO
# Match Moe:
# 1. remove DC bias
# 2. first-order high-pass filter
# ============================================================

def preprocess_audio(audio):

    audio = np.asarray(
        audio,
        dtype=np.float64
    )

    # Ensure exactly 500 ms
    if len(audio) < AUDIO_SAMPLES:

        audio = np.pad(
            audio,
            (
                0,
                AUDIO_SAMPLES - len(audio)
            )
        )

    elif len(audio) > AUDIO_SAMPLES:

        audio = audio[
            :AUDIO_SAMPLES
        ]

    # --------------------------------------------------------
    # Remove DC
    # --------------------------------------------------------

    mean = np.mean(
        audio
    )

    centered = (
        audio - mean
    )

    # --------------------------------------------------------
    # High-pass filter
    # Same equation as Moe's Pico code
    # --------------------------------------------------------

    filtered = np.zeros(
        AUDIO_SAMPLES,
        dtype=np.float64
    )

    previous_input = 0.0
    previous_output = 0.0

    for i in range(
        AUDIO_SAMPLES
    ):

        current = (
            HPF_ALPHA
            * (
                previous_output
                + centered[i]
                - previous_input
            )
        )

        previous_input = (
            centered[i]
        )

        previous_output = (
            current
        )

        filtered[i] = (
            current
        )

    return filtered


# ============================================================
# POWER SPECTRUM
# ============================================================

def calculate_spectrum(frame):

    # Apply same Hamming window
    windowed = (
        frame
        * HAMMING_WINDOW
    )

    # Zero pad from 400 → 512
    padded = np.zeros(
        FFT_SIZE,
        dtype=np.float64
    )

    padded[
        :FRAME_SIZE
    ] = windowed

    # Real FFT
    fft_result = np.fft.rfft(
        padded,
        n=FFT_SIZE
    )

    # Same power definition as Moe:
    # real^2 + imag^2
    power = (
        fft_result.real ** 2
        + fft_result.imag ** 2
    )

    return power


# ============================================================
# CUSTOM MFCC
# Match Moe's implementation
# ============================================================

def calculate_mfcc(power_spectrum):

    mel_energy = np.zeros(
        MEL_FILTERS,
        dtype=np.float64
    )

    # --------------------------------------------------------
    # Mel filter bank
    # --------------------------------------------------------

    for m in range(
        MEL_FILTERS
    ):

        left = MEL_BINS[m]
        centre = MEL_BINS[m + 1]
        right = MEL_BINS[m + 2]

        energy = 0.0

        # Rising triangle
        if centre > left:

            for k in range(
                left,
                centre
            ):

                weight = (
                    (k - left)
                    / (centre - left)
                )

                energy += (
                    power_spectrum[k]
                    * weight
                )

        # Falling triangle
        if right > centre:

            for k in range(
                centre,
                right
            ):

                weight = (
                    (right - k)
                    / (right - centre)
                )

                energy += (
                    power_spectrum[k]
                    * weight
                )

        mel_energy[m] = np.log(
            energy + EPSILON
        )

    # --------------------------------------------------------
    # DCT
    #
    # Moe skips coefficient 0.
    # We calculate coefficients 1–5.
    # --------------------------------------------------------

    mfcc = np.zeros(
        MFCC_COUNT,
        dtype=np.float64
    )

    for c in range(
        MFCC_COUNT
    ):

        coefficient = (
            c + 1
        )

        result = 0.0

        for m in range(
            MEL_FILTERS
        ):

            result += (
                mel_energy[m]
                * np.cos(
                    np.pi
                    * coefficient
                    * (m + 0.5)
                    / MEL_FILTERS
                )
            )

        mfcc[c] = result

    return mfcc


# ============================================================
# EXTRACT 10 FEATURES FROM ONE FRAME
# ============================================================

def extract_frame_features(frame):

    # --------------------------------------------------------
    # RMS
    # --------------------------------------------------------

    rms = np.sqrt(
        np.sum(
            frame ** 2
        )
        / FRAME_SIZE
    )

    # --------------------------------------------------------
    # FFT
    # --------------------------------------------------------

    power = calculate_spectrum(
        frame
    )

    # --------------------------------------------------------
    # Spectral features
    # --------------------------------------------------------

    first_bin = int(
        np.ceil(
            MIN_FREQ
            * FFT_SIZE
            / SAMPLE_RATE
        )
    )

    last_bin = int(
        np.floor(
            MAX_FREQ
            * FFT_SIZE
            / SAMPLE_RATE
        )
    )

    weighted_sum = 0.0
    magnitude_sum = 0.0

    low_energy = 0.0
    mid_energy = 0.0
    high_energy = 0.0

    for bin_index in range(
        first_bin,
        last_bin + 1
    ):

        frequency = (
            bin_index
            * SAMPLE_RATE
            / FFT_SIZE
        )

        bin_power = (
            power[bin_index]
        )

        magnitude = np.sqrt(
            bin_power
        )

        # Spectral centroid
        weighted_sum += (
            frequency
            * magnitude
        )

        magnitude_sum += (
            magnitude
        )

        # Frequency bands
        if frequency < LOW_END:

            low_energy += (
                bin_power
            )

        elif frequency < MID_END:

            mid_energy += (
                bin_power
            )

        else:

            high_energy += (
                bin_power
            )

    if magnitude_sum > EPSILON:

        centroid = (
            weighted_sum
            / magnitude_sum
        )

    else:

        centroid = 0.0

    # --------------------------------------------------------
    # Band ratios
    # --------------------------------------------------------

    total_energy = (
        low_energy
        + mid_energy
        + high_energy
        + EPSILON
    )

    low_ratio = (
        low_energy
        / total_energy
    )

    mid_ratio = (
        mid_energy
        / total_energy
    )

    high_ratio = (
        high_energy
        / total_energy
    )

    # --------------------------------------------------------
    # MFCC
    # --------------------------------------------------------

    mfcc = calculate_mfcc(
        power
    )

    # --------------------------------------------------------
    # 10 frame features
    # --------------------------------------------------------

    return np.array([
        rms,
        centroid,
        low_ratio,
        mid_ratio,
        high_ratio,
        mfcc[0],
        mfcc[1],
        mfcc[2],
        mfcc[3],
        mfcc[4],
    ])


# ============================================================
# FINAL 20-VALUE VECTOR
# ============================================================

def extract_features(audio):

    # Same preprocessing as Pico
    filtered_audio = preprocess_audio(
        audio
    )

    frame_features = []

    # Exactly 48 frames
    for frame_index in range(
        NUM_FRAMES
    ):

        offset = (
            frame_index
            * HOP_SIZE
        )

        frame = filtered_audio[
            offset:
            offset + FRAME_SIZE
        ]

        features = extract_frame_features(
            frame
        )

        frame_features.append(
            features
        )

    frame_features = np.array(
        frame_features
    )

    # Same aggregation as Moe
    means = np.mean(
        frame_features,
        axis=0
    )

    stds = np.std(
        frame_features,
        axis=0,
        ddof=0
    )

    # 10 means + 10 standard deviations
    feature_vector = np.concatenate([
        means,
        stds
    ])

    return feature_vector


# ============================================================
# SIMPLE TEST
# ============================================================

if __name__ == "__main__":

    import librosa

    test_file = (
        "ml/data/lecturer_speech/"
        "lecturer_000.wav"
    )

    audio, _ = librosa.load(
        test_file,
        sr=SAMPLE_RATE,
        mono=True
    )

    # Take first 500 ms
    audio = audio[
        :AUDIO_SAMPLES
    ]

    features = extract_features(
        audio
    )

    print(
        "Number of features:",
        len(features)
    )

    print(
        "FEATURE_VECTOR=["
        + ",".join(
            f"{value:.6f}"
            for value in features
        )
        + "]"
    )