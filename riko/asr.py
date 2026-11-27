"""Her ears: record your voice (push-to-talk or hands-free) and turn it into text.

asr: local -> Faster-Whisper on your PC
asr: groq  -> Groq's online Whisper
"""
import io
import os
import re

import numpy as np
import sounddevice as sd
import soundfile as sf
try:
    import webrtcvad
    _vad = webrtcvad.Vad(2)  # Mode 2: balanced neural voice detector filtering out fan hiss & room noise
except ImportError:
    webrtcvad = None
    _vad = None
from faster_whisper import WhisperModel
from openai import OpenAI

from riko.config import need_key

SAMPLE_RATE = 16000                # what Whisper & WebRTC VAD expect
WHISPER_MODEL = "base.en"          # bigger = more accurate, slower: small.en, medium.en
WHISPER_DEVICE = "cpu"             # "cuda" for an NVIDIA GPU (needs CUDA + cuDNN)
GROQ_MODEL = "whisper-large-v3-turbo"

_whisper = None  # Faster-Whisper model, loaded once by check()


COMMON_HALLUCINATIONS = {
    "thanks for watching.", "thanks for watching",
    "subscribe", "subtitles by", "music", "[music]", "(music)",
    "...", ".", "♪", "♫",
    "senpai talking with riko", "senpai talking with riko.",
    "while you're at it", "while you're at it.",
    "thank you.", "thank you",
    "hello, how can i help you today?",
    "hello, how can i help you today? let me know what topic, question or task you'd like to work on.",
    "let me know what topic, question or task you'd like to work on.",
    "how can i help you today?",
    "thank you for watching.", "thank you for watching",
    "you're welcome.", "you're welcome"
}


def check(cfg):
    global _whisper
    if cfg["asr"] == "groq":
        need_key("GROQ_API_KEY", "asr: groq")
    else:
        _whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8")


def find_input_device(cfg=None):
    """Finds preferred microphone input device or falls back to system default."""
    pref = cfg.get("mic_device") if cfg else None
    devices = sd.query_devices()
    if pref and str(pref).lower() not in ["default", "auto", ""]:
        pref_str = str(pref).lower()
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and pref_str in d.get("name", "").lower():
                return idx
    # System default input device
    def_in = sd.default.device[0]
    return def_in if def_in is not None and def_in >= 0 else None


def record_push_to_talk(cfg=None):
    """Push-to-talk: Enter to start, Enter to stop."""
    device_idx = find_input_device(cfg)
    input("\nPress ENTER to talk...")
    chunks = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device_idx,
                        callback=lambda data, *_: chunks.append(data.copy())):
        input("Recording... press ENTER to stop")
    if not chunks:
        return None
    audio = np.concatenate(chunks)
    wav = io.BytesIO()
    sf.write(wav, audio, SAMPLE_RATE, format="WAV")
    return wav.getvalue()


def record_vad(silence_duration=0.8, min_speech_duration=0.30, max_duration=10.0, on_speech_start=None, allow_barge_in=True, vad_threshold=0.005, cfg=None):
    """Hands-free voice detection powered by WebRTC VAD and dynamic ambient noise calibration."""
    device_idx = find_input_device(cfg)
    dev_name = sd.query_devices(device_idx)['name'] if device_idx is not None else "Default Mic"
    
    # 20ms frame = 320 samples at 16000Hz (exact standard frame for WebRTC VAD)
    frame_size = int(SAMPLE_RATE * 0.02)  # 320 samples
    chunks = []
    pre_buffer = []
    speaking = False
    silence_chunks = 0
    voice_frames = 0
    interrupt_frames = 0
    max_silence = max(15, int(silence_duration / 0.02))   # ~40 frames for 0.8s
    max_total_chunks = int(max_duration / 0.02)          # ~500 frames for 10s

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=frame_size, device=device_idx) as stream:
        # Sample ambient background noise for 200ms (10 frames)
        noise_samples = []
        for _ in range(10):
            d, _ = stream.read(frame_size)
            noise_samples.append(d)
            pre_buffer.append(d.copy())
        
        flat_noise = np.concatenate(noise_samples).astype(np.float32) / 32768.0
        ambient_rms = float(np.sqrt(np.mean(flat_noise**2)))
        speech_threshold = max(vad_threshold, ambient_rms * 1.30)

        from riko import viewer

        while True:
            data, _ = stream.read(frame_size)
            raw_bytes = data.tobytes()
            float_data = data.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(float_data**2)))

            # Neural WebRTC VAD speech check
            if _vad:
                try:
                    vad_voice = _vad.is_speech(raw_bytes, SAMPLE_RATE)
                except Exception:
                    vad_voice = False
            else:
                vad_voice = (rms > speech_threshold)

            # Check if Riko is currently outputting speech through speakers
            try:
                is_talking = viewer.is_playing()
            except Exception:
                is_talking = False

            if is_talking:
                if not allow_barge_in:
                    pre_buffer.clear()
                    voice_frames = 0
                    interrupt_frames = 0
                    continue

                # Barge-in: requires genuine voice formants + elevated energy over speaker bleed
                barge_threshold = max(0.08, speech_threshold * 4.0)
                if vad_voice and rms > barge_threshold:
                    interrupt_frames += 1
                else:
                    interrupt_frames = max(0, interrupt_frames - 1)
                user_is_speaking = (interrupt_frames >= 3)
            else:
                interrupt_frames = 0
                if not speaking:
                    # Idle state: require 2 consecutive frames (40ms) of real voice
                    is_candidate = (vad_voice and rms > speech_threshold * 0.75) or (rms > speech_threshold * 1.6)
                    if is_candidate:
                        voice_frames += 1
                    else:
                        voice_frames = max(0, voice_frames - 1)
                        # Adaptively update ambient noise floor
                        ambient_rms = 0.98 * ambient_rms + 0.02 * rms
                        speech_threshold = max(vad_threshold, ambient_rms * 1.30)
                    user_is_speaking = (voice_frames >= 2)
                else:
                    # Speaking state: maintain speech as long as VAD detects voice or energy remains elevated
                    user_is_speaking = vad_voice or (rms > speech_threshold * 0.70)

            if user_is_speaking:
                if not speaking:
                    speaking = True
                    if on_speech_start:
                        try:
                            on_speech_start()
                        except Exception:
                            pass
                    chunks.extend(pre_buffer)
                chunks.append(data.copy())
                silence_chunks = 0
            elif speaking:
                chunks.append(data.copy())
                silence_chunks += 1
                if silence_chunks >= max_silence or len(chunks) >= max_total_chunks:
                    break
            else:
                pre_buffer.append(data.copy())
                if len(pre_buffer) > 20:  # 400ms pre-buffer prevents clipped initial consonants
                    pre_buffer.pop(0)

    if not chunks:
        return None
    audio = np.concatenate(chunks)
    duration = len(audio) / SAMPLE_RATE
    if duration < min_speech_duration:
        return None

    # Sanity check: ensure valid vocal energy
    peak_val = float(np.max(np.abs(audio))) / 32768.0
    if peak_val < 0.005:
        return None

    wav = io.BytesIO()
    sf.write(wav, audio, SAMPLE_RATE, subtype="PCM_16", format="WAV")
    return wav.getvalue()


def record(cfg=None, on_speech_start=None):
    if cfg and cfg.get("hands_free"):
        barge_in = cfg.get("barge_in", True)
        handler = on_speech_start if barge_in else None
        return record_vad(
            silence_duration=cfg.get("silence_duration", 0.8),
            min_speech_duration=cfg.get("min_speech_duration", 0.30),
            max_duration=cfg.get("max_duration", 10.0),
            on_speech_start=handler,
            allow_barge_in=barge_in,
            vad_threshold=cfg.get("vad_threshold", 0.005),
            cfg=cfg
        )
    return record_push_to_talk(cfg=cfg)


def transcribe(wav_bytes, cfg):
    if cfg["asr"] == "groq":
        filename = "voice.ogg" if wav_bytes.startswith(b"OggS") else "you.wav"
        groq = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1", timeout=10.0, max_retries=1)
        try:
            # Force target language decoding (defaults to 'en') to prevent language-detection drift
            asr_lang = cfg.get("asr_language", "en")
            req_kwargs = {
                "model": GROQ_MODEL,
                "file": (filename, wav_bytes),
                "temperature": 0.0,
            }
            if asr_lang:
                req_kwargs["language"] = asr_lang

            resp = groq.audio.transcriptions.create(**req_kwargs)
            text = resp.text
        except Exception as e:
            print(f"[asr error] {e}", flush=True)
            return ""
    else:
        asr_lang = cfg.get("asr_language", "en")
        segments, _ = _whisper.transcribe(io.BytesIO(wav_bytes), temperature=0.0, language=asr_lang)
        text = "".join(s.text for s in segments)
    
    clean_text = text.strip().strip("\"'., ")
    clean_lower = clean_text.lower()

    # Reject empty, single punctuation, or fewer than 2 alphanumeric letters (e.g. '.', '...', '?', 'a')
    alnum_chars = re.findall(r"[a-zA-Z0-9]", clean_text)
    if len(alnum_chars) < 2:
        return ""

    # Reject foreign CJK script hallucinations (Chinese, Japanese, Korean)
    # Riko communicates in English, Hindi, and Hinglish in Latin script
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", clean_text):
        return ""

    # Reject common Whisper hallucinations when audio contains silence/background noise
    for phrase in COMMON_HALLUCINATIONS:
        if clean_lower == phrase:
            return ""
        if len(phrase) > 3 and phrase in clean_lower:
            return ""

    return text.strip()


if __name__ == "__main__":
    # Talk into your mic and see what she hears: uv run python -m riko.asr
    from riko.config import load_config
    cfg = load_config()
    check(cfg)
    print("You said:", transcribe(record(cfg), cfg))
