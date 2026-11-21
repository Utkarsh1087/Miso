"""Voice Identification & Speaker Biometrics for Riko.
Enrolls Utkarsh Senpai's acoustic voiceprint and verifies whether incoming microphone
speech belongs to Senpai or an unfamiliar stranger!
"""
import io
from typing import Optional, Tuple, Union

import numpy as np
import sounddevice as sd
import soundfile as sf

from riko.config import ROOT

VOICEPRINT_DIR = ROOT / "character_files"
ENROLLED_VOICEPRINT_PATH = VOICEPRINT_DIR / "senpai_voiceprint.npy"
ENROLLED_VOICE_SAMPLE_PATH = VOICEPRINT_DIR / "senpai_voice.wav"

SAMPLE_RATE = 16000
DEFAULT_SIMILARITY_THRESHOLD = 0.92


def has_enrolled_voice() -> bool:
    """Returns True if senpai's voiceprint has been enrolled and saved."""
    return ENROLLED_VOICEPRINT_PATH.exists()


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _build_mel_filterbank(n_filters: int = 26, n_fft: int = 512, sample_rate: int = 16000) -> np.ndarray:
    """Builds triangular Mel filterbank matrix."""
    low_mel = _hz_to_mel(100.0)
    high_mel = _hz_to_mel(min(sample_rate / 2.0, 7500.0))
    mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
    hz_points = _mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    fbank = np.zeros((n_filters, int(n_fft // 2 + 1)), dtype=np.float32)
    for m in range(1, n_filters + 1):
        f_m_minus = bin_points[m - 1]
        f_m = bin_points[m]
        f_m_plus = bin_points[m + 1]

        for k in range(f_m_minus, f_m):
            if f_m != f_m_minus:
                fbank[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)
        for k in range(f_m, f_m_plus):
            if f_m_plus != f_m:
                fbank[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)

    return fbank


def extract_voiceprint(audio_input: Union[bytes, np.ndarray], sample_rate: int = SAMPLE_RATE) -> Optional[np.ndarray]:
    """Extracts a normalized acoustic speaker embedding (MFCC + Delta + Formant Centroids).
    Returns a 50-dimensional unit vector, or None if audio is silent or too short.
    """
    if isinstance(audio_input, (bytes, bytearray)):
        try:
            audio, sr = sf.read(io.BytesIO(audio_input))
            if sr != sample_rate:
                # Basic linear resample if sample rate differs
                new_len = int(len(audio) * sample_rate / sr)
                audio = np.interp(np.linspace(0, len(audio), new_len), np.arange(len(audio)), audio)
        except Exception:
            return None
    else:
        audio = np.array(audio_input, dtype=np.float32)

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    audio = audio.astype(np.float32)
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val

    frame_len = int(0.025 * sample_rate)  # 25ms window (400 samples)
    hop = int(0.010 * sample_rate)        # 10ms step (160 samples)

    if len(audio) < frame_len * 4:
        return None

    # Energy-based voice activity detection (filter silence)
    num_raw_frames = (len(audio) - frame_len) // hop
    rms = np.array([np.sqrt(np.mean(audio[i * hop : i * hop + frame_len] ** 2)) for i in range(num_raw_frames)])
    voiced_indices = np.where(rms > 0.015)[0]

    # Require at least 8 voiced frames (~80ms of actual vocalization)
    if len(voiced_indices) < 8:
        return None

    frames = np.array([audio[i * hop : i * hop + frame_len] * np.hanning(frame_len) for i in voiced_indices])
    n_fft = 512
    mag = np.abs(np.fft.rfft(frames, n_fft))
    power = (mag ** 2) / n_fft

    # Mel-frequency filterbank
    fbank = _build_mel_filterbank(n_filters=26, n_fft=n_fft, sample_rate=sample_rate)
    filter_banks = np.dot(power, fbank.T)
    filter_banks = np.where(filter_banks == 0, np.finfo(float).eps, filter_banks)
    log_fb = np.log(filter_banks)

    # 16 MFCC coefficients (excluding C0 to eliminate volume dependence)
    num_ceps = 16
    n = np.arange(26)
    dct_m = np.cos(np.pi * np.outer(np.arange(1, num_ceps + 1), 2 * n + 1) / (2.0 * 26.0))
    mfcc = np.dot(log_fb, dct_m.T)

    # Delta MFCCs (first-order velocity)
    if len(mfcc) > 2:
        delta = (mfcc[2:] - mfcc[:-2]) / 2.0
        delta_mean = np.mean(delta, axis=0)
    else:
        delta_mean = np.zeros(num_ceps)

    mfcc_mean = np.mean(mfcc, axis=0)
    mfcc_std = np.std(mfcc, axis=0)

    # Spectral centroid (frequency register / timbre brightness)
    freqs = np.linspace(0, sample_rate / 2.0, int(n_fft // 2 + 1))
    sc = np.sum(mag * freqs, axis=1) / (np.sum(mag, axis=1) + 1e-9)
    sc_mean = np.mean(sc) / (sample_rate / 2.0)
    sc_std = np.std(sc) / (sample_rate / 2.0)

    # Concatenate into 50-dimensional acoustic fingerprint
    feature_vec = np.concatenate([mfcc_mean, mfcc_std, delta_mean, [sc_mean, sc_std]])
    feature_vec = feature_vec - np.mean(feature_vec)
    norm = np.linalg.norm(feature_vec)
    if norm > 0:
        feature_vec = feature_vec / norm

    return feature_vec.astype(np.float32)


def enroll_voice(audio_input: Optional[Union[bytes, np.ndarray]] = None, sample_rate: int = SAMPLE_RATE) -> Tuple[bool, str]:
    """Enrolls senpai's voiceprint permanently.
    If `audio_input` is None, records 4.5 seconds live from the microphone.
    """
    if audio_input is None:
        print("\n[voice_id] Recording Senpai's voice for 4.5 seconds... Speak now!")
        duration = 4.5
        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        audio = recording.flatten()
    elif isinstance(audio_input, (bytes, bytearray)):
        audio, sr = sf.read(io.BytesIO(audio_input))
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)
        if sr != sample_rate:
            new_len = int(len(audio) * sample_rate / sr)
            audio = np.interp(np.linspace(0, len(audio), new_len), np.arange(len(audio)), audio)
    else:
        audio = np.array(audio_input, dtype=np.float32).flatten()

    voiceprint = extract_voiceprint(audio, sample_rate=sample_rate)
    if voiceprint is None:
        return False, "I couldn't hear your voice clearly, senpai! Please speak louder and clearly without background noise."

    VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(str(ENROLLED_VOICEPRINT_PATH), voiceprint)
    sf.write(str(ENROLLED_VOICE_SAMPLE_PATH), audio, sample_rate)

    print(f"[voice_id] Enrolled Senpai's voiceprint to: {ENROLLED_VOICEPRINT_PATH}")
    return True, "I have memorized your voice, Utkarsh senpai! From now on, I will always recognize you whenever you speak to me~"


def verify_speaker(
    audio_input: Union[bytes, np.ndarray],
    sample_rate: int = SAMPLE_RATE,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Tuple[bool, float, str]:
    """Compares the incoming audio against senpai's enrolled voiceprint.
    Returns: (is_senpai: bool, similarity_score: float, status_label: str)
    """
    if not has_enrolled_voice():
        return True, 1.0, "not_enrolled"

    current_voiceprint = extract_voiceprint(audio_input, sample_rate=sample_rate)
    if current_voiceprint is None:
        return False, 0.0, "audio_too_short"

    try:
        enrolled_voiceprint = np.load(str(ENROLLED_VOICEPRINT_PATH))
    except Exception as e:
        print(f"[voice_id load error] {e}")
        return True, 1.0, "load_error"

    # Pearson correlation score between zero-centered unit embeddings
    score = float(np.dot(current_voiceprint, enrolled_voiceprint))

    if score >= threshold:
        return True, score, "senpai_verified"
    else:
        return False, score, "stranger_detected"

